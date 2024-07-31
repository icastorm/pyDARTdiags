import pandas as pd
import datetime as dt
import numpy as np
import os
import yaml

class obs_sequence:
    """Create an obs_sequence object from an ascii observation
       sequence file.

       Attributes:
       
           df : pandas Dataframe containing all the observations
           all_obs : list of all observations, each observation is a list
           header : header from the ascii file
           vert : dictionary of dart vertical units
           types : dictionary of types in the observation sequence file
           copie_names : names of copies in the observation sequence file.
                         Spelled copie to avoid conflict with python built-in copy function.
                         Spaces are replaced with underscores in copie_names.
           file : the input observation sequence ascii file
       
       usage: 
         Read the observation sequence from file:
              obs_seq = obs_sequence('/home/data/obs_seq.final.ascii.small')
         Access the resulting pandas dataFrame:
              obs_seq.df   

       For 3D sphere models: latitude and longitude are in degrees in the DataFrame
       sq_err = (mean-obs)**2
       bias = (mean-obs)

       rmse = sqrt( sum((mean-obs)**2)/n )
       bias = sum((mean-obs)/n)
       spread = sum(sd)
       totalspread = sqrt(sum(sd+obs_err_var)) 

       
    """
    ## static variables
    # vertrical coordinate:
    #   undefined 'VERTISUNDEF'
    #   surface 'VERTISSURFACE' (value is surface elevation in m)
    #   model level 'VERTISLEVEL'
    #   pressure 'VERTISPRESSURE' (in pascals)
    #   height 'VERTISHEIGHT' (in meters)
    #   scale height 'VERTISSCALEHEIGHT' (unitless)
    vert = {-2: 'undefined',              
            -1: 'surface (m)', 
             1: 'model level',
             2: 'pressure (Pa)',
             3: 'height (m)',
             4: 'scale height' }

    # synonyms for observation
    synonyms_for_obs = ['NCEP BUFR observation',
                        'AIRS observation', 
                        'GTSPP observation', 
                        'SST observation',
                        'observations']
    
    def __init__(self, file):
        self.loc_mod = 'None'
        self.file = file
        self.header, self.header_n = self.read_header(file)
        self.types = self.collect_obs_types(self.header)
        self.copie_names, self.n_copies = self.collect_copie_names(self.header)
        self.seq = self.obs_reader(file, self.n_copies)
        self.all_obs = self.create_all_obs() # uses up the generator
        # at this point you know if the seq is loc3d or loc1d
        if self.loc_mod == 'None':
            raise ValueError("Neither 'loc3d' nor 'loc1d' could be found in the observation sequence.")
        self.columns = self.column_headers()
        self.df = pd.DataFrame(self.all_obs, columns = self.columns)
        if self.loc_mod == 'loc3d':
            self.df['longitude'] = np.deg2rad(self.df['longitude'])
            self.df['latitude'] = np.deg2rad(self.df['latitude'])
        # rename 'X observation' to observation
        self.synonyms_for_obs = [synonym.replace(' ', '_') for synonym in self.synonyms_for_obs]
        rename_dict = {old: 'observation' for old in self.synonyms_for_obs  if old in self.df.columns}
        self.df = self.df.rename(columns=rename_dict)
        # calculate bias and sq_err is the obs_seq is an obs_seq.final
        if 'prior_ensemble_mean'.casefold() in map(str.casefold, self.columns):
            self.df['bias'] = (self.df['prior_ensemble_mean'] - self.df['observation'])
            self.df['sq_err'] = self.df['bias']**2  # squared error
        module_dir = os.path.dirname(__file__)
        self.default_composite_types = os.path.join(module_dir,"composite_types.yaml")

    def create_all_obs(self):
        """ steps through the generator to create a
            list of all observations in the sequence 
        """
        all_obs = []
        for obs in self.seq:
            data = self.obs_to_list(obs)
            all_obs.append(data)
        return all_obs

    def obs_to_list(self, obs):
        """put single observation into a list
           discards obs_def
        """
        data = []
        data.append(obs[0].split()[1]) # obs_num
        data.extend(list(map(float,obs[1:self.n_copies+1]))) # all the copies
        try:  # HK todo only have to check loc3d or loc1d for the first observation, the whole file is the same
            locI = obs.index('loc3d')
            location = obs[locI+1].split()
            data.append(float(location[0]))  # location x
            data.append(float(location[1]))  # location y
            data.append(float(location[2]))  # location z
            data.append(obs_sequence.vert[int(location[3])])
            self.loc_mod = 'loc3d'
        except ValueError:
            try:
                locI = obs.index('loc1d')
                location = obs[locI+1]
                data.append(float(location))  # 1d location 
                self.loc_mod = 'loc1d'
            except ValueError:
                raise ValueError("Neither 'loc3d' nor 'loc1d' could be found in the observation sequence.")
        typeI = obs.index('kind') # type of observation
        type_value = obs[typeI + 1]
        data.append(self.types[type_value]) # observation type
        # any observation specific obs def info is between here and the end of the list
        time = obs[-2].split()
        data.append(int(time[0])) # seconds
        data.append(int(time[1])) # days
        data.append(convert_dart_time(int(time[0]), int(time[1]))) # datetime   # HK todo what is approprate for 1d models?
        data.append(float(obs[-1])) # obs error variance ?convert to sd?
        
        return data

    def column_headers(self):
        """define the columns for the dataframe """
        heading = []
        heading.append('obs_num')
        heading.extend(self.copie_names)
        if self.loc_mod == 'loc3d':
            heading.append('longitude')
            heading.append('latitude')
            heading.append('vertical')
            heading.append('vert_unit')
        elif self.loc_mod == 'loc1d':
            heading.append('location')
        heading.append('type')
        heading.append('seconds')
        heading.append('days')
        heading.append('time')
        heading.append('obs_err_var')
        return heading

    @staticmethod
    def read_header(file):
        """Read the header and number of lines in the header of an obs_seq file"""
        header = []
        with open(file, 'r') as f:
            for line in f:
                if "first:" in line and "last:" in line:
                    break
                else:
                    header.append(line.strip())
        return header, len(header)

    @staticmethod
    def collect_obs_types(header):
        """Create a dictionary for the observation types in the obs_seq header"""
        num_obs_types = int(header[2])
        types = dict([x.split() for  x in header[3:num_obs_types+3]])
        return types

    @staticmethod
    def collect_copie_names(header):
        """
        Extracts the names of the copies from the header of an obs_seq file.


        Parameters:
        header (list): A list of strings representing the lines in the header of the obs_seq file.

        Returns:
        tuple: A tuple containing two elements:
            - copie_names (list): A list of strings representing the copy names with _ for spaces.
            - len(copie_names) (int): The number of copy names.
        """
        for i, line in enumerate(header):
            if "num_obs:" in line and "max_num_obs:" in line:
                first_copie = i+1
                break
        copie_names = ['_'.join(x.split()) for x in header[first_copie:]]
        return copie_names, len(copie_names)

    @staticmethod
    def obs_reader(file, n):
        """Reads the obs sequence file and returns a generator of the obs"""
        previous_line = ''
        with open(file, 'r') as f:     
            for line in f:
                if "OBS" in line or "OBS" in previous_line:
                    if "OBS" in line:
                        obs = []
                        obs.append(line.strip()) 
                        for i in range(n+100): # number of copies + 100.  Needs to be bigger than any metadata
                            try:
                                next_line = next(f)
                            except:
                                yield obs
                                StopIteration
                                return
                            if "OBS" in next_line:
                                previous_line = next_line
                                break
                            else:
                                obs.append(next_line.strip())
                        yield obs
                    elif "OBS" in previous_line: # previous line is because I cannot use f.tell with next
                        obs = []
                        obs.append(previous_line.strip()) 
                        obs.append(line.strip()) 
                        for i in range(n+100): # number of copies + 100.  Needs to be bigger than any metadata
                            try:
                                next_line = next(f)
                            except:
                                yield obs
                                StopIteration
                                return
                            if "OBS" in next_line:
                                previous_line = next_line
                                break
                            else:
                                obs.append(next_line.strip())
                                previous_line = next_line
                        yield obs

    def composite_types(self, composite_types='use_default'):
        """
        Set up and construct composite types for the DataFrame.

        This function sets up composite types based on a provided YAML configuration or 
        a default configuration. It constructs new composite rows by combining specified 
        components and adds them to the DataFrame.

        Parameters:
        composite_types (str, optional): The YAML configuration for composite types.
                                        If 'use_default', the default configuration is used.
                                        Otherwise, a custom YAML configuration can be provided.

        Returns:
        pd.DataFrame: The updated DataFrame with the new composite rows added.

        Raises:
        Exception: If there are repeat values in the components.
        """

        if composite_types == 'use_default':
            composite_yaml = self.default_composite_types
        else:
            composite_yaml = composite_types
        self.composite_types_dict  = load_yaml_to_dict(composite_yaml)
        
        components = []
        for value in self.composite_types_dict.values():
            components.extend(value["components"])

        if len(components) != len(set(components)):
            raise Exception("There are repeat values in components.")

        df_comp = self.df[self.df['type'].str.upper().isin([component.upper() for component in components])]
        df_no_comp = self.df[~self.df['type'].str.upper().isin([component.upper() for component in components])]

        for key in self.composite_types_dict:
            df_new = construct_composit(df_comp, key, self.composite_types_dict[key]['components'])
            df_no_comp = pd.concat([df_no_comp, df_new], axis=0)

        return df_no_comp
        
def load_yaml_to_dict(file_path):
    """
    Load a YAML file and convert it to a dictionary.

    Parameters:
    - file_path (str): The path to the YAML file.

    Returns:
    - dict: The YAML file content as a dictionary.
    """
    try:
        with open(file_path, 'r') as file:
            return yaml.safe_load(file)
    except Exception as e:
        print(f"Error loading YAML file: {e}")
        return None        


def convert_dart_time(seconds, days):
    """covert from seconds, days after 1601 to datetime object

    base year for Gregorian calendar is 1601
    dart time is seconds, days since 1601
    """
    time = dt.datetime(1601,1,1) + dt.timedelta(days=days, seconds=seconds)
    return time
    
def select_by_dart_qc(df, dart_qc):
    """
    Selects rows from a DataFrame based on the DART quality control flag.

    Parameters:
    df (DataFrame): A pandas DataFrame.
    dart_qc (int): The DART quality control flag to select.

    Returns:
    DataFrame: A DataFrame containing only the rows with the specified DART quality control flag.

    Raises:
    ValueError: If the DART quality control flag is not present in the DataFrame.
    """
    if dart_qc not in df['DART_quality_control'].unique():
        raise ValueError(f"DART quality control flag '{dart_qc}' not found in DataFrame.")
    else:
        return df[df['DART_quality_control'] == dart_qc]

def select_failed_qcs(df):
    """
    Selects rows from a DataFrame where the DART quality control flag is greater than 0.

    Parameters:
    df (DataFrame): A pandas DataFrame.

    Returns:
    DataFrame: A DataFrame containing only the rows with a DART quality control flag greater than 0.
    """
    return df[df['DART_quality_control'] > 0]

def possible_vs_used(df):
    """
    Calculates the count of possible vs. used observations by type.

    This function takes a DataFrame containing observation data, including a 'type' column for the observation
    type and an 'observation' column. The number of used observations ('used'), is the total number
    minus the observations that failed quality control checks (as determined by the `select_failed_qcs` function).
    The result is a DataFrame with each observation type, the count of possible observations, and the count of
    used observations.

    Parameters:
    - df (pd.DataFrame): A DataFrame with at least two columns: 'type' for the observation type and 'observation'
      for the observation data. It may also contain other columns required by the `select_failed_qcs` function
      to determine failed quality control checks.

    Returns:
    - pd.DataFrame: A DataFrame with three columns: 'type', 'possible', and 'used'. 'type' is the observation type,
      'possible' is the count of all observations of that type, and 'used' is the count of observations of that type
      that passed quality control checks.

    """
    possible = df.groupby('type')['observation'].count()
    possible.rename('possible', inplace=True)
    used = df.groupby('type')['observation'].count() - select_failed_qcs(df).groupby('type')['observation'].count()
    used.rename('used', inplace=True)
    return pd.concat([possible, used], axis=1).reset_index()


def construct_composit(df_comp, composite, components):
    """
    Construct a composite DataFrame by combining rows from two components.

    This function takes two DataFrames and combines rows from them based on matching
    location and time. It creates a new row with a composite type by combining 
    specified columns using the square root of the sum of squares method.

    Parameters:
    df_comp (pd.DataFrame): The DataFrame containing the component rows to be combined.
    composite (str): The type name for the new composite rows.
    components (list of str): A list containing the type names of the two components to be combined.

    Returns:
    merged_df (pd.DataFrame): The updated DataFrame with the new composite rows added.
    """
    selected_rows = df_comp[df_comp['type'] == components[0].upper()]
    selected_rows_v = df_comp[df_comp['type'] == components[1].upper()]

    columns_to_combine = df_comp.filter(regex='ensemble').columns.tolist()
    columns_to_combine.append('observation')  # TODO HK: bias, sq_err, obs_err_var
    merge_columns = ['latitude', 'longitude', 'vertical', 'time']

    print("duplicates in u: ", selected_rows[merge_columns].duplicated().sum())
    print("duplicates in v: ",selected_rows_v[merge_columns].duplicated().sum())

    # Merge the two DataFrames on location and time columns
    merged_df = pd.merge(selected_rows, selected_rows_v, on=merge_columns, suffixes=('', '_v'))

    # Apply the square root of the sum of squares method to the relevant columns
    for col in columns_to_combine:
        merged_df[col] = np.sqrt(merged_df[col]**2 + merged_df[f'{col}_v']**2)

    # Create the new composite rows
    merged_df['type'] = composite.upper()
    merged_df = merged_df.drop(columns=[col for col in merged_df.columns if col.endswith('_v')])

    return merged_df
