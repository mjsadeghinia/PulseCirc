#%%
from pathlib import Path
import logging
import cardiac_geometries
import pulse
import dolfin
import ufl_legacy as ufl
from pulse.solver import NonlinearSolver
from pulse.solver import NonlinearProblem
import copy

import numpy as np
import matplotlib.pyplot as plt
import activation_model
from pulse.utils import getLogger
logger = getLogger(__name__)


#%%Parameters

t_res=1000
t_span = (0.0, 1.0)
# Aortic Pressure: the pressure from which the ejection start
P_ao=5

#%%
def get_ellipsoid_geometry(folder=Path("lv")):
    if not folder.is_dir():
        # Create geometry
        cardiac_geometries.create_lv_ellipsoid(
            folder,
            create_fibers=True,
        )

    geo = cardiac_geometries.geometry.Geometry.from_folder(folder)
    marker_functions = pulse.MarkerFunctions(cfun=geo.cfun, ffun=geo.ffun, efun=geo.efun)
    microstructure = pulse.Microstructure(f0=geo.f0, s0=geo.s0, n0=geo.n0)
    return pulse.HeartGeometry(
        mesh=geo.mesh,
        markers=geo.markers,
        marker_functions=marker_functions,
        microstructure=microstructure,
    )

geometry = get_ellipsoid_geometry()

#%%
t_eval = np.linspace(*t_span, t_res)
normal_activation_params = activation_model.default_parameters()
normal_activation = (
    activation_model.activation_function(
        t_span=t_span,
        t_eval=t_eval,
        parameters=normal_activation_params,
    )
    / 2000.0
)
systole_ind=np.where(normal_activation == 0)[0][-1]+1
normal_activation_systole=normal_activation[systole_ind:]
t_eval_systole=t_eval[systole_ind:]
# make a simple activation for testing
normal_activation_systole=np.linspace(0,50,200)[1:]
t_eval_systole=np.linspace(0,0.5,200)[1:]
# %% Defining activation as dolfin.constant

activation = dolfin.Constant(0.0, name='gamma')

#%% Material Properties
matparams = pulse.HolzapfelOgden.default_parameters()
material = pulse.HolzapfelOgden(
    activation=activation,
    active_model="active_stress",
    parameters=matparams,
    f0=geometry.f0,
    s0=geometry.s0,
    n0=geometry.n0,
)
#%% Boundary Conditions
# Add spring term at the epicardium of stiffness 1.0 kPa/cm^2 to represent pericardium
# Fix the basal plane in the longitudinal direction
# 0 in V.sub(0) refers to x-direction, which is the longitudinal direction
def fix_basal_plane(W):
    V = W if W.sub(0).num_sub_spaces() == 0 else W.sub(0)
    bc = dolfin.DirichletBC(
        V.sub(0),
        dolfin.Constant(0.0),
        geometry.ffun,
        geometry.markers["BASE"][0],
    )
    return bc

def fix_basal_endo_ring(W):
    V = W if W.sub(0).num_sub_spaces() == 0 else W.sub(0)
    bc = dolfin.DirichletBC(
        V,
        dolfin.Constant((0.0,0.0,0.0)),
        geometry.efun,
        geometry.markers["ENDORING"][0],
        method = "pointwise",
    )
    return bc

# print(dir(fix_basal_endo_ring))
edgs=[]
for edge in dolfin.edges(geometry.mesh):
    # breakpoint()
    if geometry.efun[edge]==geometry.markers['BASAL-ANTERIOR'][0]:
        # print(geometry.efun[edge])
        for vertex in dolfin.vertices(edge):
            edgs.append(vertex.point().array())
            # r=np.sqrt(vertex.point().array()[1]**2+vertex.point().array()[2]**2)
            # print([vertex.point().array()[0],vertex.point().array()[1],vertex.point().array()[2]])
edgs=np.array(edgs)            
plt.scatter(edgs[:,1],edgs[:,2])           
# print(dir(fix_basal_endo_ring))
pnts=[]
radii=[]
for fc in dolfin.facets(geometry.mesh):
    # breakpoint()
    if geometry.ffun[fc]==geometry.markers['BASE'][0]:
        # print(geometry.ffun[fc])
        for vertex in dolfin.vertices(fc):
            pnts.append(vertex.point().array())
            # r=np.sqrt(vertex.point().array()[1]**2+vertex.point().array()[2]**2)
            # print([vertex.point().array()[0],vertex.point().array()[1],vertex.point().array()[2]])
pnts=np.array(pnts)            
plt.scatter(pnts[:,1],pnts[:,2])
plt.axis('equal')
rad_vals=np.min((pnts[:,1]**2+pnts[:,2]**2))

# class EndoRing(dolfin.SubDomain):
#     def inside(self, x, on_boundary):
#         return dolfin.near(x[0], 5, dolfin.DOLFIN_EPS) and dolfin.near(x[1]**2+x[2]**2, 44.76124567474048, dolfin.DOLFIN_EPS)



class EndoRing(dolfin.SubDomain):
    def inside(self, x, on_boundary):
        return dolfin.near(x[0], 5, 0.001) and dolfin.near(pow(x[1],2)+pow(x[2],2), 44.76124, 0.001)


W=problem.state_space.sub(0)
V = dolfin.VectorFunctionSpace(geometry.mesh, "Lagrange", 1)

bc21 = dolfin.DirichletBC(W.sub(1), dolfin.Constant(0.0), EndoRing(), method="pointwise")

u_ = dolfin.FunctionSpace(W)
u_.vector()[:] = 10
bc21.apply(u_.vector())
dolfin.File("u.pvd") <<u_



dirichlet_bc = (fix_basal_plane,)


# LV Pressure
lvp = dolfin.Constant(0.0, name='LV Pressure')
lv_marker = geometry.markers["ENDO"][0]
lv_pressure = pulse.NeumannBC(traction=lvp, marker=lv_marker, name="lv")
neumann_bc = [lv_pressure]

# Collect boundary conditions
bcs = pulse.BoundaryConditions(
    dirichlet=dirichlet_bc,
    neumann=neumann_bc,
    # robin=robin_bc,
)
#%%
problem = pulse.MechanicsProblem(geometry, material, bcs)

outdir = Path("results_pulse_circ")
outdir.mkdir(exist_ok=True, parents=True)
outname = Path(outdir) / "results.xdmf"
if outname.is_file():
    outname.unlink()
    outname.with_suffix(".h5").unlink()
    
#%%
vols=[]
pres=[]
# Saving the initial pressure and volume
v_current=geometry.cavity_volume()
p_current=lvp.values()[0]
vols.append(v_current)
pres.append(p_current)
# %% Initialization to the atrium pressure of 0.2 kPa
pulse.iterate.iterate(problem, lvp, 0.02, initial_number_of_steps=15)
v_current=geometry.cavity_volume(u=problem.state.sub(0))
p_current=lvp.values()[0]
vols.append(v_current)
pres.append(p_current)
reults_u, p = problem.state.split(deepcopy=True)
reults_u.t=0
with dolfin.XDMFFile(outname.as_posix()) as xdmf:
    xdmf.write_checkpoint(reults_u, "u", float(0), dolfin.XDMFFile.Encoding.HDF5, True)
# %%
tau=t_eval_systole[1]
p_ao=1

#%%
def WK2(tau,p_ao,p_old,p_current,R,C):
    if p_current>p_ao:
        dp=(p_current-p_old)/tau
        Q=p_current/R+dp*C
    else:
        Q=0
    return Q
def dV_FE(problem):
    """
    Calculating the dV/dP based on FE model. 
    
    :pulse.MechanicsProblem problem:    The mechanics problem containg the infromation on FE model.
    
    """
    #
    #  Backup the problem
    state_backup_dv = problem.state.copy(deepcopy=True)
    lvp_value_backup_dv=get_lvp_from_problem(problem).values()[0]
    #
    #
    lvp=get_lvp_from_problem(problem)
    p_old=lvp.values()[0]
    v_old=get_lvv_from_problem(problem)
    dp0=0.001*p_old
    dp=dp0
    k=0
    flag_solved=False
    while (not flag_solved) and k<20:
        try:
            p_new=p_old+dp
            lvp.assign(p_new)
            problem.solve()
            flag_solved=True
        except pulse.mechanicsproblem.SolverDidNotConverge:
            problem.state.assign(state_backup_dv)
            lvp.assign(lvp_value_backup_dv)
            # problem.solve()
            dp+=dp0
            print(f"Derivation not Converged, increasin the dp to : {dp}")
            k+=1
        
    # pulse.iterate.iterate(dummy_problem, dummy_lvp, p_new, initial_number_of_steps=5)
    v_new=get_lvv_from_problem(problem)
    dVdp=(v_new-v_old)/(p_new-p_old)
    problem.state.assign(state_backup_dv)
    lvp.assign(lvp_value_backup_dv)
    # FIXME: I think we need to solve the problem here too
    # problem.solve()
    return dVdp
    
def dV_WK2(fun,tau,p_old,p_current,R,C):
    eval1=fun(tau,p_ao,p_old,p_current,R,C)
    eval2=fun(tau,p_ao,p_old,p_current*1.01,R,C)
    return (eval2-eval1)/(p_current*.01)



def get_lvp_from_problem(problem):
    # getting the LV pressure which is assinged as Neumann BC from a Pulse.MechanicsProblem
    return problem.bcs.neumann[0].traction
def get_lvv_from_problem(problem):
    # getting the LV volume from a Pulse.MechanicsProblem and its solution
    return problem.geometry.cavity_volume(u=problem.state.sub(0))

#%%
for t in range(len(normal_activation_systole)):
    print('================================')
    print("Applying Contraction...")
    target_activation=normal_activation_systole[t]
    pulse.iterate.iterate(problem, activation, target_activation)
    print('================================')
    print("Finding the corresponding LV pressure...")
    #### Circulation
    circ_iter=0
    # initial guess for new pressure
    if t==0:
        p_current=p_current*1.01
    else:
        p_current=pres[-1]+(pres[-1]-pres[-2])
    #
    #  Backup the problem
    state_backup = problem.state.copy(deepcopy=True)
    lvp_value_backup=get_lvp_from_problem(problem).values()[0]
    #
    #
    problem.solve()
    p_old=pres[-1]
    v_old=vols[-1]
    R=[]
    tol=0.0001*v_old
    while len(R)==0 or (np.abs(R[-1])>tol and circ_iter<10):
        pi=0
        p_steps=2
        k=0
        flag_solved=False
        while k<10 and not flag_solved:
            p_list=np.linspace(float(lvp), p_current, p_steps)[1:]
            for pi in p_list:
                print(pi)
                try:
                    lvp.assign(pi)
                    problem.solve()
                    flag_solved=True
                except pulse.mechanicsproblem.SolverDidNotConverge:
                    problem.state.assign(state_backup)
                    lvp.assign(lvp_value_backup)
                    problem.solve()
                    p_steps+=1
                    k+=1
                    flag_solved=False
                    print(f"Problem not Converged, reset to initial problem and increasing the steps to : {p_steps}")
                    break;
        v_current=get_lvv_from_problem(problem)
        Q=WK2(tau,p_ao,p_old,p_current,0.01,1)
        v_fe=v_current
        v_circ=v_old-Q
        R.append(v_fe-v_circ)
        if np.abs(R[-1])>tol:
            dVFE_dP=dV_FE(problem)
            dQCirc_dP=dV_WK2(WK2,tau,p_old,p_current,0.01,1)
            J=dVFE_dP+dQCirc_dP
            p_current=p_current-R[-1]/J
            circ_iter+=1
    # Assign the new state (from problem_circ) to the problem to use as estimation for iterate problem
    # problem.state.assign(problem_circ.state)
    p_current=get_lvp_from_problem(problem).values()[0]
    # lvp.assign(p_current)
    # problem.solve()
    # pulse.iterate.iterate(problem, lvp, p_current)
    v_current=get_lvv_from_problem(problem)
    vols.append(v_current)
    pres.append(p_current)
    # print('================================')
    # print(f"Time Step: {t}, is converged with Circulation Residuals of : {R}")
    print(f"Time Step: {t} is converged")
    # print(f"The pressures are : {pres}")
    # print(f"The volumes are : {vols}")
    print('================================')
    reults_u, p = problem.state.split(deepcopy=True)
    reults_u.t=t+1
    with dolfin.XDMFFile(outname.as_posix()) as xdmf:
        xdmf.write_checkpoint(reults_u, "u", float(t), dolfin.XDMFFile.Encoding.HDF5, True)
    if t>15:
        break
    
# %%
