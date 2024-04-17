#%%
import numpy as np
from pathlib import Path

import cardiac_geometries
import pulse
import dolfin


#%%
class HeartModelPulse:
    def __init__(self, geo_params: dict = None, geo_folder: Path = Path("lv_test")):
        """
        Initializes the heart model with given geometrical parameters and folder for geometrical data.

        Parameters:
        geo_params (dict, optional): Dictionary of geometric parameters.
        geo_folder (Path): Path object indicating the folder where geometry data is stored.
        """
        self.lv_pressure = dolfin.Constant(0.0, name='LV Pressure')
        self.activation = dolfin.Constant(0.0, name='Activation')

        if geo_params is None:
            geo_params = self.get_default_geo_params()
        self.geometry = self.get_ellipsoid_geometry(geo_folder, geo_params)
        self.material = self.get_material_model()
        self.bcs = self.apply_bcs()
        self.problem = pulse.MechanicsProblem(self.geometry, self.material, self.bcs)

        
    def compute_volume(self, activation_value: float, pressure_value: float) -> float:
        """
        Computes the volume of the heart model based on activation and pressure values.

        Parameters:
        activation_value (float): The activation value to be applied.
        pressure_value (float): The pressure value to be applied.

        Returns:
        float: The computed volume of the heart model.
        """
        pulse.iterate.iterate(self.problem, (self.activation, self.lv_pressure), (activation_value, pressure_value))
        volume_current = self.problem.geometry.cavity_volume(u=self.problem.state.sub(0))
        return volume_current
    
    
    def compute_volume_derivation(self, activation_value: float, pressure_value: float) -> float: ...
        
    def get_pressure(self) -> float:

        return float(self.lv_pressure)

    def get_volume(self) -> float:

        return self.compute_volume(self.activation, self.lv_pressure)  # Assumes compute_volume is correct for current state

    
    def save(self, t: float, outname: Path = Path("results.xdmf")):
        """
        Saves the current state of the heart model at a given time to a specified file.

        Parameters:
        t (float): The time at which to save the model state.
        outname (Path): The file path to save the model state.
        """
        results_u, _ = self.problem.state.split(deepcopy=True)
        results_u.t = t
        with dolfin.XDMFFile(outname.as_posix()) as xdmf:
            xdmf.write_checkpoint(results_u, "u", float(t + 1), dolfin.XDMFFile.Encoding.HDF5, True)


    def get_ellipsoid_geometry(self, folder: Path, geo_props: dict):
        """
        Generates the ellipsoid geometry based on cardiac_geometries, for info look at caridiac_geometries.

        Parameters:
        folder (Path): The directory to save or read the geometry.
        geo_props (dict): Geometric properties for the ellipsoid model.

        Returns:
        A geometry object compatible with the pulse.MechanicsProblem.
        """
        geo = cardiac_geometries.mesh.create_lv_ellipsoid(
            outdir=folder,
            r_short_endo=geo_props["r_short_endo"],
            r_short_epi=geo_props["r_short_epi"],
            r_long_endo=geo_props["r_long_endo"],
            r_long_epi=geo_props["r_long_epi"],
            psize_ref=geo_props["mesh_size"],
            mu_apex_endo=-np.pi,
            mu_base_endo=-np.arccos(geo_props["r_short_epi"] / geo_props["r_long_endo"] / 2),
            mu_apex_epi=-np.pi,
            mu_base_epi=-np.arccos(geo_props["r_short_epi"] / geo_props["r_long_epi"] / 2),
            create_fibers=True,
            fiber_angle_endo=-60,
            fiber_angle_epi=60,
            fiber_space="P_1",
            aha=True,
        )
        marker_functions = pulse.MarkerFunctions(cfun=geo.cfun, ffun=geo.ffun, efun=geo.efun)
        microstructure = pulse.Microstructure(f0=geo.f0, s0=geo.s0, n0=geo.n0)
        return pulse.HeartGeometry(
            mesh=geo.mesh,
            markers=geo.markers,
            marker_functions=marker_functions,
            microstructure=microstructure,
        )
  
    
    def get_material_model(self):
        """
        Constructs the material model for the heart using default parameters.

        Returns:
        A material model object for use in a pulse.MechanicsProblem.
        """
        matparams = pulse.HolzapfelOgden.default_parameters()
        return pulse.HolzapfelOgden(
            activation=self.activation,
            active_model="active_stress",
            parameters=matparams,
            f0=self.geometry.f0,
            s0=self.geometry.s0,
            n0=self.geometry.n0,
        )

    def apply_bcs(self):
        bcs = pulse.BoundaryConditions(
            dirichlet=(self._dirichlet_bc,),
            neumann=self._neumann_bc(),
        )
        return bcs
        
        
        
    def _dirichlet_bc(self, W):
        # V = W if W.sub(0).num_sub_spaces() == 0 else W.sub(0)
        
        # # Fixing the base in x[0] direction
        # bc_fixed_based = dolfin.DirichletBC(
        #     V.sub(0),
        #     dolfin.Constant(0.0),
        #     self.geometry.ffun,
        #     self.geometry.markers["BASE"][0],
        # )
        
        # # Fixing the endo ring in all directions to prevent rigid body motion
        # endo_ring_points=self._get_endo_ring()
        # endo_ring_points_x0=np.mean(endo_ring_points[:,0])
        # endo_ring_points_radius=np.sqrt(np.min((endo_ring_points[:,1]**2+endo_ring_points[:,2]**2)))
        
        # class EndoRing_subDomain(dolfin.SubDomain):
        #     def __init__(self, x0, x2):
        #         super().__init__()
        #         self.x0 = x0
        #         self.x2 = x2
        #         print(x0)
        #     def inside(self, x, on_boundary):
        #         return dolfin.near(x[0], self.x0, .01) and dolfin.near(pow(pow(x[1],2)+pow(x[2],2),0.5), self.x2, .1)
            
        # endo_ring_fixed=dolfin.DirichletBC(
        #     V,
        #     dolfin.Constant((0.0,0.0,0.0)),
        #     EndoRing_subDomain(endo_ring_points_x0,endo_ring_points_radius),
        #     method="pointwise",
        # )
        # return [bc_fixed_based,endo_ring_fixed]

        V = W if W.sub(0).num_sub_spaces() == 0 else W.sub(0)
        
        # Fixing the base in x[0] direction
        bc_fixed_based = dolfin.DirichletBC(
            V,
            dolfin.Constant((0.0,0.0,0.0)),
            self.geometry.ffun,
            self.geometry.markers["BASE"][0],
        )
        
        return bc_fixed_based
        
        
    def _neumann_bc(self):
        # LV Pressure
        lv_marker = self.geometry.markers["ENDO"][0]
        lv_pressure = pulse.NeumannBC(traction=self.lv_pressure, marker=lv_marker, name="lv")
        neumann_bc = [lv_pressure]
        return neumann_bc 
    
    def _get_endo_ring(self):
        endo_ring_points=[]
        for fc in dolfin.facets(self.geometry.mesh):
            if self.geometry.ffun[fc]==self.geometry.markers['BASE'][0]:
                for vertex in dolfin.vertices(fc):
                    endo_ring_points.append(vertex.point().array())
        endo_ring_points=np.array(endo_ring_points)
        return endo_ring_points
    
    
    @staticmethod
    def get_default_geo_params():
        """
        Default geometrical parameter for the left ventricle
        """
        return {
            "r_short_endo": 3,
            "r_short_epi": 3.75,
            "r_long_endo": 5,
            "r_long_epi": 5.5,
            "mesh_size": 3,
        }
    

# %%
results_name='results.xdmf'
outdir = Path("testing")
outdir.mkdir(exist_ok=True, parents=True)
outname = Path(outdir) / results_name
if outname.is_file():
    outname.unlink()
    outname.with_suffix(".h5").unlink()

activation=np.linspace(0,10,10)
pressure=np.linspace(0,1,10)

model = HeartModelPulse()
model.compute_volume(0,0)
model.save(0, outname=outname)
for t, (a,p) in enumerate(zip(activation,pressure)):
    model.compute_volume(a,p)
    model.save(t+1, outname=outname)
    
# %%
