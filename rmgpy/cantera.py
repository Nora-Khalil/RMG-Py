import os
import yaml
import cantera as ct
#from ck2cti import SurfaceArrhenius 

from rmgpy.chemkin import load_chemkin_file
from rmgpy.species import Species
from rmgpy.reaction import Reaction
from rmgpy.thermo.nasa import NASAPolynomial, NASA
from rmgpy.thermo.wilhoit import Wilhoit
from rmgpy.kinetics.arrhenius import Arrhenius, PDepArrhenius, MultiArrhenius, MultiPDepArrhenius
from rmgpy.kinetics.falloff import Troe, ThirdBody, Lindemann
from rmgpy.kinetics.chebyshev import Chebyshev
from rmgpy.data.solvation import SolventData
from rmgpy.kinetics.surface import StickingCoefficient, SurfaceArrhenius
from rmgpy.util import make_output_subdirectory     #checked
from datetime import datetime
from rmgpy.chemkin import get_species_identifier







#make final chem.yml file with newest model
def convert_chemkin_to_cantera(chemkin_path, dictionary_path=None, output="chem.yml"):
    if dictionary_path:
        spcs, rxns = load_chemkin_file(chemkin_path, dictionary_path=dictionary_path)
    else:
        spcs, rxns = load_chemkin_file(chemkin_path)
    write_cantera(spcs, rxns, path=output)


def write_cantera(spcs, rxns, solvent=None, solvent_data=None, path="chem.yml"):
    result_dict = get_mech_dict(spcs, rxns, solvent=solvent, solvent_data=solvent_data)
    with open(path, 'w') as f:
        #generator line
        f.write('generator: RMG\n')

        # datetime object containing current date and time
        now = datetime.now()
        dt_string = now.strftime("%a, %d %b %Y %H:%M:%S")
        f.write(f'date: {dt_string}\n')

        #units line
        f.write("\nunits: {length: cm, time: s, quantity: mol, activation-energy: kcal/mol}\n")
        f.write('\n') 

        #'phases' line (below)


        block1 = \
        '''
phases:
- name: gas
  thermo: ideal-gas
  elements: [H, D, T, C, Ci, O, Oi, N, Ne, Ar, He, Si, S, F, Cl, Br, I, X]'''
        f.write(block1)

        #'species' section in phases section

        sorted_species = sorted(spcs, key=lambda spcs: spcs.index)
        species_to_write = [get_species_identifier(spec) for spec in sorted_species]

        block2 = \
        f'''
  species: [{', '.join(species_to_write)}]
  kinetics: gas'''

        f.write(block2)

        block3 = \
        '''
  transport: mixture-averaged
  state: {T: 300.0, P: 1 atm}
        ''' 
        f.write(block3)

        block4 = \
        '''
elements:
- symbol: Ci
  atomic-weight: 13.003
- symbol: D
  atomic-weight: 2.014
- symbol: Oi
  atomic-weight: 17.999
- symbol: T
  atomic-weight: 3.016
- symbol: X
  atomic-weight: 195.083

'''
        f.write(block4)

        yaml.dump(result_dict, stream=f, sort_keys=False)




def get_radicals(spc):
    if spc.molecule[0].to_smiles() == "[O][O]":  # treat oxygen as stable to improve radical analysis
        return 0
    else:
        return spc.molecule[0].multiplicity-1



###will have to edit this section!!!
def get_mech_dict(spcs, rxns, solvent='solvent', solvent_data=None):

     names = [x.label for x in spcs]
     for i,name in enumerate(names): #fix duplicate names
         if names.count(name) > 1:
             names[i] += "-"+str(names.count(name))
     
     is_surface = False
     for spc in spcs:
         if spc.contains_surface_site():
             is_surface = True
             break
         if not is_surface:
             result_dict = dict()
             result_dict["species"]= [obj_to_dict(x, spcs, names=names) for x in spcs]

             reactions = []
             for rmg_rxn in rxns:
                 reactions.extend(reaction_to_dicts(rmg_rxn, spcs)) 
             result_dict["reactions"] = reactions

     return result_dict


def reaction_to_dicts(obj, spcs):
    """
    Takes an RMG reaction object (obj), returns a list of dictionaries
    for YAML properties. Most reaction objects the list will be of 
    length 1, but a MultiArrhenius or MultiPDepArrhenius will be longer.
    """

    try:
        reaction_list = []
        if isinstance(obj.kinetics, MultiArrhenius) or isinstance(obj.kinetics, MultiPDepArrhenius):
            list_of_cantera_reactions = obj.to_cantera(use_chemkin_identifier=True)
        else: 
            list_of_cantera_reactions = [ obj.to_cantera(use_chemkin_identifier=True) ]

        for reaction in list_of_cantera_reactions:
            reaction_data = reaction.input_data     
            efficiencies = getattr(obj.kinetics, 'efficiencies', {})
            if efficiencies:      
                reaction_data["efficiencies"] = {spcs[i].to_chemkin(): float(val) for i, val in enumerate(obj.kinetics.get_effective_collider_efficiencies(spcs)) if val != 1}

            reaction_list.append(reaction_data)
        return reaction_list
    except: 
        print('passing')
        print(type(obj.kinetics))
        print(str(obj))
        return []


def obj_to_dict(obj, spcs, names=None, label="solvent"):

    result_dict = dict()

    if isinstance(obj, Species):
        s  = obj.to_cantera(use_chemkin_identifier=True)
        species_data = s.input_data
        try: 
            result_dict['note'] = obj.transport_data.comment
        except:
            pass
        species_data.update(result_dict)
        return species_data #returns composition, name, thermo, and transport, and note
            

class CanteraWriter(object):
    """
    This class listens to a RMG subject
    and writes an YAML file with the current state of the RMG model,
    to a yaml subfolder.


    A new instance of the class can be appended to a subject as follows:

    rmg = ...
    listener = CanteraWriter(outputDirectory)
    rmg.attach(listener)

    Whenever the subject calls the .notify() method, the
    .update() method of the listener will be called.

    To stop listening to the subject, the class can be detached
    from its subject:

    rmg.detach(listener)

    """
    def __init__(self, output_directory=''):
        super(CanteraWriter, self).__init__()
        self.output_directory = output_directory
        make_output_subdirectory(output_directory, 'cantera')

    def update(self, rmg):
        solvent_data = None
        if rmg.solvent:
            solvent_data = rmg.database.solvation.get_solvent_data(rmg.solvent)
        write_cantera(rmg.reaction_model.core.species, rmg.reaction_model.core.reactions, solvent=rmg.solvent, solvent_data=solvent_data,
                  path=os.path.join(self.output_directory, 'cantera', 'chem{}.yaml').format(len(rmg.reaction_model.core.species)))