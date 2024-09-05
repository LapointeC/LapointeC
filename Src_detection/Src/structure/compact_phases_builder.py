import os
import numpy as np
from warnings import warn
from .lattice import SolidAse
from .compact_phases_library import MetaOctahedron, Octa, MetaIcosahedron, Ico

from ase.io import write
from ase import Atoms, Atom

import xml.etree.ElementTree as ET
import random
from typing import List, Dict, Tuple, TypedDict


class InputsCompactPhases(TypedDict) :
    a0 : float
    element : str
    scale_factor : float


##############
## C15
##############
class C15Center(TypedDict) : 
    center : np.ndarray
    type : str

class C15Builder : 
    def __init__(self, dict_param : InputsCompactPhases, 
                 path_inputs : os.PathLike[str] = 'XML') -> None : 
        self.octahedron = MetaOctahedron()
        self.dict_param = dict_param
        self.path_inputs = path_inputs

        self.centerC15 : Dict[int, C15Center] = {}
        self.size = None
        self.cubic_supercell_unit : Atoms = None
        self.extra_atom  : Atoms = None
        self.C15_system : Atoms = None

        if os.path.exists(path_inputs) : 
            self.InputsParser()
            self.cubic_supercell_unit, self.size = self.build_cubic_supercell()

    def InputsParser(self) -> None : 
        """Read XML file correspondinf to the center of C15 atoms"""
        xml_root = ET.parse(self.path_inputs)
        for xml_param in xml_root.getroot() : 
            if xml_param.tag == 'Centers':
                for id_cent, cent in enumerate(xml_param) : 
                    if not id_cent in self.centerC15.keys() : 
                        self.centerC15[id_cent] = {}
                    self.centerC15[id_cent]['center'] = np.array([int(el) for el in cent.text.split()])

            if xml_param.tag == 'Type':
                for id_type, type in enumerate(xml_param) : 
                    if not id_type in self.centerC15.keys() : 
                        self.centerC15[id_type] = {}
                    self.centerC15[id_type]['type'] = type.text

        self.check_out_parser()

    def check_out_parser(self) -> None :
        """Check if contain of XML file is coherent !""" 
        for key in self.centerC15.keys() : 
            if [k for k in self.centerC15[key].keys()] not in [['type', 'center'],['center', 'type']] :
                raise TimeoutError(f'Missing type or center for {key}')

    def compute_cell_size(self) -> List[int] : 
        """Compute the size of the cubic supercell to put the dislocation
        
        Returns
        -------

        List[int]
            Replication list for ```SolidAse```
        """
        center_coordinate = np.array([val['center'] for _, val in self.centerC15.items()])
        size = self.dict_param['scale_factor']*np.amax(center_coordinate)
        return [int(size) for _ in range(3)]
    
    def compute_cell_size_draft(self, size :float) -> List[int] : 
        """Compute the size of the cubic supercell to put the dislocation
        
        Returns
        -------

        List[int]
            Replication list for ```SolidAse```
        """
        rbox = size*self.dict_param['scale_factor']
        return [int(np.ceil(rbox/self.dict_param['a0'])) for _ in range(3)]

    def build_cubic_supercell(self, draft : bool = False, size = 1.0) -> Tuple[Atoms, int] :
        """Build the initial ```Atoms``` object """
        if draft : 
            size_list = self.compute_cell_size_draft(size)
        else :
            size_list = self.compute_cell_size()
        print(f'... Cubic supercell : {size_list}')
        solid_ase_obj = SolidAse(size_list, 
                        self.dict_param['element'], 
                        1.0)
        return solid_ase_obj.structure('BCC'), size_list[0]

    def compute_number_perfect_C15(self, minimal_size : float, size : float) -> int : 
        """Compute the number of perfect C15 to put in the whole ```C15``` cluster
        
        Parameters
        ----------

        minimal_size : float 
            Minimal size of C15 cluster

        size : float 
            Size of the C15 cluster

        Returns 
        -------

        int 
            Number of perfect C15 clusters to put
        """
        return int((np.ceil(size/minimal_size) + 1)**2)

    def AgnosticPerfectC15Cluster(self, cluster_size : float) -> None : 
        """Build agnostically C15 cluster and update ```C15Center``` dictionnary
        
        Parameters
        ----------

        cluster_size : float 
            Size of the cluster 
        """

        minimal_cluster_size = np.sqrt(3)*self.dict_param['a0']
        
        # Here is the minimal size case for C15 cluster
        if cluster_size < minimal_cluster_size : 
            warn(f'Minimal size for perfect C15 cluster is {minimal_cluster_size} AA')
            self.cubic_supercell_unit, self.size = self.build_cubic_supercell(draft=True, size=minimal_cluster_size)
            center_coordinates = np.array([ int(np.ceil(0.5*self.size)) for _ in range(3) ])
            self.centerC15[0] = {'center':center_coordinates,
                                 'type':'type1'}

        else :
            self.cubic_supercell_unit, self.size = self.build_cubic_supercell(draft=True, size=cluster_size)
            Nb_C15 = self.compute_number_perfect_C15(minimal_cluster_size, cluster_size) 
            center_coordinates = np.array([ int(np.ceil(0.5*self.size)) for _ in range(3) ])
            
            change_type = {'type1':'type2',
                           'type2':'type1'}
            self.explorated_dict = {'center':center_coordinates,
                                    'type':'type2',
                                    'link':random.shuffle(self.octahedron.typeOcta['type1'].link.tolist())}
            self.centerC15[0] = {'center':center_coordinates,
                                 'type':'type1'}
            
            for idx_C15 in range(1,Nb_C15) : 
                # We have to change the cluster center !
                if idx_C15%len(self.explorated_dict['link']) == 0 : 
                    new_idx_center = random.sample( [idx for idx in range(idx_C15-1-len(self.explorated_dict['link']),idx_C15-1)] )
                    new_center = self.centerC15[new_idx_center]['center']
                    new_type_center = change_type[self.centerC15[new_idx_center]['type']]
                    self.explorated_dict = {'center':new_center,
                                            'type':new_type_center,
                                            'link':random.shuffle(self.octahedron.typeOcta[new_type_center].link.tolist())}

                idx_direction = idx_C15%len(self.explorated_dict['link'])
                new_center = center_coordinates + self.explorated_dict['link'][idx_direction]
                self.centerC15[idx_C15] = {'center':new_center,
                                               'type':self.explorated_dict['type']}

        return 

    def build_C15_system(self, tolerance : float = 1e-3) -> Atoms :
        """Build ```C15``` clusters from ```C15Center``` dictionnary
        
        Parameters
        ----------

        tolerance : float 
            Norm tolerance to consider if atoms are identical

        Returns
        -------

        Atoms 
            ```Atoms``` object containing C15 clusters
        """ 
        C15_atoms = Atoms()
        list_position_C15 = []

        # put all gaos config in C15 cluster
        for _, C15_center in self.centerC15.items() : 
            center_coordinate = C15_center['center']
            # loop over tetrahedron !
            for id_tetra, tetra in enumerate(self.octahedron.typeOcta[C15_center['type']].atom.T) : 
                # loop over gaos sites !
                for gaos_tetra in self.octahedron.typeOcta[C15_center['type']].gaos[:,:,id_tetra] :     
                    new_C15_position = center_coordinate + tetra + 0.5*gaos_tetra
                    if len(list_position_C15) > 0 : 
                        distance_array = np.linalg.norm(np.array(list_position_C15) - new_C15_position, axis = 1)
                        # C15 positions already in cluster
                        if np.amin(distance_array) < tolerance :
                            continue
                        else : 
                            list_position_C15.append(new_C15_position)
                            C15_atoms.append( Atom( self.dict_param['element'], new_C15_position ) )

                    else :
                        # Add first C15 position ! 
                        list_position_C15.append(new_C15_position)
                        C15_atoms.append( Atom( self.dict_param['element'], new_C15_position ) )

        #C15_atoms.set_array('defect',
        #                    np.ones(len(C15_atoms),),
        #                    dtype=float)
        return C15_atoms
    
    def remove_atoms_in_system(self, system : Atoms, tolerance : float = 1e-3) -> Atoms :
        """Removing from ```removeatom``` attribute in order to put C15 into bulk system
        
        Parameters
        ----------

        system : Atoms 
            ```Atoms``` object where ```removeatom``` will be removed

            
        tolerance : float 
            Norm tolerance to consider if atoms are identical

        Returns
        -------

        Atoms 
            ```Atoms``` object where ```removeatom``` have been removed
        
        """
        ToRemoveCoordinate = np.array([ self.octahedron.typeOcta[val['type']].removeatom.T + val['center'] for _, val in self.centerC15.items() ])
        ToRemoveCoordinate = ToRemoveCoordinate.reshape((3,len(self.centerC15)*6)).T

        list_idx2remove = []
        for idx, pos in enumerate(system.positions) : 
            array_distance_idx = np.linalg.norm( ToRemoveCoordinate - pos, axis = 1)
            if np.amin(array_distance_idx) < tolerance : 
                list_idx2remove.append(idx)

        new_system = system.copy()
        del new_system[[idx for idx in list_idx2remove]]
        
        return new_system

    def write_C15(self, atoms : Atoms, path_writing : os.PathLike[str], format : str) -> None :
        """Write geometry file for dislocation loop 
        
        Parameters
        ----------

        atoms : Atoms 
            ```Atoms``` object containing the C15 clusters

        path_writing : os.PathLike[str]
            Path to the C15 clusters geometry file to write 

        format : str 
            Type geometry file to write (```lammps```, ```vasp``` ...)
        """
        write(path_writing, atoms, format=format)
        return         

    def BuildC15Cluster(self,
                        writing_path : os.PathLike[str] = './C15.geom',
                        format : str = 'vasp',
                        ovito_mode : bool = False) -> None : 
        """Build C15 system from ```C15Center``` dictionnary 
        
        Parameters
        ----------

        writing_path : os.Pathlike[str]
            Writing path for ```C15``` clusters geometry file

        format : str 
            Type geometry file to write (```lammps```, ```vasp``` ...)
        """
        
        #Build C15 system
        C15_atoms = self.build_C15_system()
        self.extra_atom = self.remove_atoms_in_system(C15_atoms)
        
        #Assign defect value for C15 system ...
        self.extra_atom.set_array('defect',
                            np.ones(len(self.extra_atom),),
                            dtype=float)       

        print(f'... I put {len(self.extra_atom)} C15 atoms in the system')

        Natoms_bulk = len(self.cubic_supercell_unit)
        self.cubic_supercell_unit = self.remove_atoms_in_system(self.cubic_supercell_unit)

        #Assign defect value for bulk system ...
        self.cubic_supercell_unit.set_array('defect',
                            np.zeros(len(self.cubic_supercell_unit),),
                            dtype=float)

        # rescale the system to have the true lattice parameter
        self.C15_system = self.cubic_supercell_unit + self.extra_atom
        lenght_scale = np.power(len(self.C15_system)/Natoms_bulk, 0.3333)
        self.C15_system.set_cell(self.cubic_supercell_unit.cell[:]*lenght_scale*self.dict_param['a0'], scale_atoms=True)
        
        if not ovito_mode :
            self.write_C15(self.C15_system,
                           writing_path,
                           format)

        return 

##############
## A15
##############
class A15Center(TypedDict) : 
    center : np.ndarray
    type : str

class A15Builder : 
    def __init__(self, dict_param : InputsCompactPhases, 
                 path_inputs : os.PathLike[str] = 'XML') -> None : 
        self.isocahedron = MetaIcosahedron()
        self.dict_param = dict_param
        self.path_inputs = path_inputs

        self.centerC15 : Dict[int, A15Center] = {}
        self.size = None
        self.cubic_supercell_unit : Atoms = None
        self.extra_atom  : Atoms = None
        self.A15_system : Atoms = None

        if os.path.exists(path_inputs) : 
            self.InputsParser()
            self.cubic_supercell_unit, self.size = self.build_cubic_supercell()

    def InputsParser(self) -> None : 
        """Read XML file correspondinf to the center of C15 atoms"""
        xml_root = ET.parse(self.path_inputs)
        for xml_param in xml_root.getroot() : 
            if xml_param.tag == 'Centers':
                for id_cent, cent in enumerate(xml_param) : 
                    if not id_cent in self.centerC15.keys() : 
                        self.centerC15[id_cent] = {}
                    self.centerC15[id_cent]['center'] = np.array([int(el) for el in cent.text.split()])

            if xml_param.tag == 'Type':
                for id_type, type in enumerate(xml_param) : 
                    if not id_type in self.centerC15.keys() : 
                        self.centerC15[id_type] = {}
                    self.centerC15[id_type]['type'] = type.text

        self.check_out_parser()

    def check_out_parser(self) -> None :
        """Check if contain of XML file is coherent !""" 
        for key in self.centerC15.keys() : 
            if [k for k in self.centerC15[key].keys()] not in [['type', 'center'],['center', 'type']] :
                raise TimeoutError(f'Missing type or center for {key}')