import numpy as np

import random
import os
from ase import Atoms

from ..metrics import MCDModel, GMMModel, PCAModel
from ..mld import DBManager

from ..tools import timeit

import scipy.stats
import matplotlib
import pickle
matplotlib.use('Agg')

from typing import List, Dict, TypedDict
import matplotlib.pyplot as plt

plt.rcParams['text.usetex'] = True
plt.rcParams['text.latex.preamble'] = r'\usepackage{amsmath}'

class Bin(TypedDict) : 
    min : float
    max : float
    list_norm : List[float]
    list_id : List[int]
    density : float

####################################################
## SQUARE NORM DESCRIPTORS CLASS
####################################################
class NormDescriptorHistogram : 
    """Selection method based on histogram of square descriptor norm. This class allows 
    to build small size dataset for MCD fitting with the same statistical properties than the original one"""
    
    def __init__(self, list_atoms : List[Atoms], nb_bin : int = None) :
        """Build the square descriptor norm histogram for a given dataset.
        
        Parameters
        ----------
        list_atoms : List[Atoms]
            Full dataset contains in Atoms object

        nb_bin : int 
            Number of bin for the histogram. If nb_bin is set to None, nb_bin = int(0.05*len(list_atoms)) by default
        
        """ 
        if nb_bin is None :
            nb_bin = int(0.05*len(list_atoms))

        self.descriptors = np.concatenate([ats.get_array('milady-descriptors') for ats in list_atoms], axis=0)
        self.nb_bin = nb_bin
        self.id_list = np.array([i for i in range(self.descriptors.shape[0])])

        self.array_norm_square = np.sum(self.descriptors**2, axis=1)
        self.bin : Dict[int, Bin] = {}

        self.min_dis, self.max_dis = np.amin(self.array_norm_square), np.amax(self.array_norm_square)
        increment = (self.max_dis - self.min_dis)/nb_bin
        #here is the histogram generation procedure
        
        for k in range(nb_bin) : 
            self.bin[k] = {'min':self.min_dis+k*increment,
                           'max':self.min_dis+(k+1)*increment,
                           'list_norm':[],
                           'list_id':[],
                           'density':None}

        self.fill_histogram()

    def fill_histogram(self) :
        """Fill the histogram based square norm of descriptors"""
        for _, bin_data in self.bin.items() : 
            mask_bin_inf = self.array_norm_square > bin_data['min']
            mask_bin_supp = self.array_norm_square <= bin_data['max']
            
            mask_bin = mask_bin_inf & mask_bin_supp
            
            bin_data['list_norm'] += self.array_norm_square[mask_bin].tolist()
            bin_data['list_id'] += self.id_list[mask_bin].tolist()

        # density correction for random choice
        sum_density = 0
        for i, data_bin in self.bin.items() : 
            random.shuffle(data_bin['list_id'])
            data_bin['density'] = float(len(data_bin['list_norm']))/float(self.descriptors.shape[0])
            sum_density += data_bin['density']
        
        miss_density = (1.0-sum_density)/(self.nb_bin)
        for _, data_bin in self.bin.items() : 
            data_bin['density'] += miss_density

    def histogram_sample(self,nb_selected : int) -> np.ndarray :
        """Histogram selection based on random choice function
        
        Parameters
        ----------

        nb_selected : int 
            Number of local configurations to select 

        Returns:
        --------

        np.ndarray
            Selected descriptors to fit data envelop
        """
        list_id_selected = []
        selection_bin = np.random.choice([k for k in range(self.nb_bin)], nb_selected, p=[data_bin['density'] for _, data_bin in self.bin.items()])
        for sl_bin in selection_bin : 
            if len(self.bin[sl_bin]['list_id']) > 0 :
                list_id_selected.append(self.bin[sl_bin]['list_id'][-1])
                self.bin[sl_bin]['list_id'].pop(-1)

        print('... Effective number of selected atoms is {:5d}/{:5d} ...'.format(len(list_id_selected),nb_selected))
        return self.descriptors[list_id_selected]

#######################################################
## MCD ANALYSIS OBJECT
#######################################################
class MCDAnalysisObject : 

    def __init__(self, dbmodel : DBManager) -> None : 
        self.dic_class : Dict[str,Dict[str,List[Atoms]]] = {}
        self.mcd_model = MCDModel()
        self.gmm_model = GMMModel()
        self.pca_model = PCAModel()

        def fill_dictionnary_fast(ats : Atoms, dic : Dict[str,List[Atoms]]) -> None : 
            symbols = ats.get_chemical_symbols()
            for sym in dic.keys() : 
                mask_sym = list(map( lambda b : b == sym, symbols))
                ats_sym = ats[mask_sym]

                dic[sym] += [ats_sym]
            return 

        for key in dbmodel.model_init_dic.keys() : 
            key_dic = key[0:6]
            if key_dic in self.dic_class.keys() : 
                fill_dictionnary_fast(dbmodel.model_init_dic[key]['atoms'],
                                      self.dic_class[key_dic])

            else : 
                species = dbmodel.model_init_dic[key]['atoms'].symbols.species()
                dic_species : Dict[str,List[Atoms]] = {sp:[] for sp in species}
                fill_dictionnary_fast(dbmodel.model_init_dic[key]['atoms'],
                                      dic_species)

                self.dic_class[key_dic] = dic_species


    def store_model_pickle(self, path_pkl : os.PathLike[str],
                         model_kind : str = '') -> None :
        """Build agnostically the pickle file for model
        
        Parameters
        ----------

        path_pkl : os.PathLike[str]
            Path to the pickle file to write 

        model_kind : str 
            Name of the model to store in the pickle file
        """
        implemented_models = ['mcd_model', 'gmm_model', 'pca_model']
        if model_kind == '' : 
            for model in implemented_models :
                if len(self.__dict__[model].models) > 0 :
                    model_kind = model 
                    break 
                    
        pickle.dump(self.__dict__[model_kind], open(path_pkl,'wb'))
        return 

    def _get_all_atoms_species(self, species : str) -> List[Atoms] : 
        """Create the full list of Atoms for a given species
        
        Parameters
        ----------

        species : str
            Species to select 

        Returns:
        --------

        List[Atoms]
            List of selected Atoms objects based on species
        """
        list_atoms_species = []
        for sub_class in self.dic_class.keys() : 
            list_atoms_species += self.dic_class[sub_class][species]
        return list_atoms_species


    def fit_mcd_envelop(self, species : str, contamination : float = 0.05, nb_bin = 100, nb_selected=10000) -> None : 
        """Perform MCD analysis for a given species
        
        TODO write doc
        """
        list_atom_species = self._get_all_atoms_species(species)
        print()
        print('... Starting histogram procedure ...')
        histogram_norm_species = NormDescriptorHistogram(list_atom_species,nb_bin=nb_bin)
        array_desc_selected = histogram_norm_species.histogram_sample(nb_selected=nb_selected)
        print(array_desc_selected.shape)
        print('... Histogram selection is done ...')
        print()

        print('... Starting MCD fit for {:} atoms ...'.format(species))
        self.mcd_model._fit_mcd_model(array_desc_selected, species, contamination=contamination)
        #self._fit_mcd_model(list_atom_species, species, contamination=contamination)
        print('... MCD envelop is fitted ...')
        updated_atoms = self.mcd_model._get_mcd_distance(list_atom_species,species)

        #mcd distribution 
        fig, axis = plt.subplots(nrows=1, ncols=2, figsize=(14,6))
        list_mcd = np.concatenate([at.get_array('mcd-distance') for at in updated_atoms], axis=0)
        n, _, patches = axis[0].hist(list_mcd,density=True,bins=50,alpha=0.7)
        for i in range(len(patches)):
            patches[i].set_facecolor(plt.cm.viridis(n[i]/max(n)))        

        #chi2 fit
        dist = getattr(scipy.stats, 'chi2')
        param = dist.fit(list_mcd)
        fake_mcd = np.linspace(np.amin(list_mcd), np.amax(list_mcd), 1000) #
        axis[0].plot(fake_mcd, dist(*param).pdf(fake_mcd), linewidth=1.5, linestyle='dashed',color='grey')
        
        # kde estimation
        self.mcd_model._fit_distribution(np.array(list_mcd), species)

        axis[0].set_xlabel(r'MCD distance $d_{\textrm{MCD}}$ for %s atoms'%(species))
        axis[0].set_ylabel(r'Probability density')

        #pca ! 
        cm = plt.cm.get_cmap('gnuplot')
        print('')
        print('... Starting PCA analysis for {:s} atoms ...'.format(species))
        desc_transform = self.pca_model._get_pca_model(list_atom_species, species, n_component=2)
        scat = axis[1].scatter(desc_transform[:,0],desc_transform[:,1],
                               c=list_mcd,
                               cmap=cm,
                               edgecolors='grey',
                               linewidths=0.5,
                               alpha=0.5)
        print('... PCA analysis is done ...'.format(species))
        axis[1].set_xlabel(r'First principal component for %s atoms'%(species))
        axis[1].set_ylabel(r'Second principal component for %s atoms'%(species))
        cbar = fig.colorbar(scat,ax=axis[1])
        cbar.set_label(r'MCD disctances $d_{\textrm{MCD}}$', rotation=270)
        plt.tight_layout()

        plt.savefig('{:s}_distribution_analysis.pdf'.format(species),dpi=300)

    def fit_gmm_envelop(self, species : str, nb_bin_histo : int =100, nb_selected :int = 10000, dict_gaussian : dict = {'n_components':2,
                                                            'covariance_type':'full',
                                                            'init_params':'kmeans'}) -> None : 
        """Perform MCD analysis for a given species
        
        TODO Same write doc 
        """
        list_atom_species = self._get_all_atoms_species(species)
        print()
        print('... Starting histogram procedure ...')
        histogram_norm_species = NormDescriptorHistogram(list_atom_species,nb_bin=nb_bin_histo)
        array_desc_selected = histogram_norm_species.histogram_sample(nb_selected=nb_selected)
        print('... Histogram selection is done ...')
        print()

        print('... Starting GMM fit for {:} atoms ...'.format(species))
        self.gmm_model._fit_gaussian_mixture_model(array_desc_selected, species, dict_gaussian=dict_gaussian)
        print('... GMM envelop is fitted ...')
        updated_atoms = self.gmm_model._get_gmm_distance(list_atom_species,species)

        fig, axis = plt.subplots(nrows=1, ncols=dict_gaussian['n_components'], figsize=(14,6))
        
        #mcd distribution 
        list_gmm = np.concatenate([at.get_array('gmm-distance') for at in updated_atoms], axis=0)
        self.gmm_model._fit_distribution(list_gmm, species)

        for k in range(dict_gaussian['n_components']) : 
            mask = k == np.argmin(list_gmm, axis=1)
            dist = getattr(scipy.stats, 'chi2')
            param = dist.fit(list_gmm[:,k][mask])
            #print(param)
            print('DOF for Gaussian {:1d} is {:1.1f}'.format(k+1,param[0]))
            if param[0] > 1.0 :
                fake_mcd = np.linspace(1.2*np.amin(list_gmm[:,k][mask]), np.amax(list_gmm[:,k][mask]), 1000) #
                axis[k].plot(fake_mcd, dist(*param).pdf(fake_mcd), linewidth=1.5, linestyle='dashed',color='grey')
            #self.distribution[species] = {'chi2':param}
            
            n, _, patches = axis[k].hist(list_gmm[:,k][mask],density=True,bins=50,alpha=0.7)
            for i in range(len(patches)):
                patches[i].set_facecolor(plt.cm.viridis(n[i]/max(n)))   
            axis[k].set_xlabel(r'GMM distance $d^{%s}_{\textrm{GMM}}$ for %s atoms'%(str(k+1),species))
            axis[k].set_ylabel(r'Probability density')
        plt.tight_layout()

        plt.savefig('{:s}_gmm_analysis.pdf'.format(species),dpi=300)

#######################################################
    
def custom_writer(atoms : Atoms, path : str, property : str = 'mcd-distance',**kwargs) : 
    """TODO Write doc"""
    if property == 'logistic-score' : 
        class_to_plot = kwargs['class_to_plot']

    dic = {el:k+1 for k, el in enumerate(atoms.symbols.species())}
    cell = atoms.cell[:]
    with open(path,'w') as w : 
        w.write('Custom writing ...\n')
        w.write('\n')
        w.write('{:5d} atoms \n'.format(atoms.get_global_number_of_atoms()))
        w.write('{:2d} atom types \n'.format(len(dic)))
        w.write('{:1.9f} {:3.9f} xlo xhi \n'.format(0,cell[0,0]))
        w.write('{:1.9f} {:3.9f} ylo zhi \n'.format(0,cell[1,1]))
        w.write('{:1.9f} {:3.9f} zlo zhi \n'.format(0,cell[2,2]))
        w.write('\n')
        w.write('\n')
        w.write('Atoms \n')
        w.write('\n')
        atoms_property = atoms.get_array(property)
        if property == 'logistic-score' :
            atoms_property = atoms_property[:,class_to_plot]

        for id, pos in enumerate(atoms.get_positions()) : 
            w.write('{:5d} {:2d} {:3.9f} {:3.9f} {:3.9f} {:3.9f} \n'.format(id+1,dic[atoms[id].symbol],atoms_property[id],pos[0],pos[1],pos[2]))
    return