# The MIT License (MIT)
#
# Copyright (c) 2021 Computer Assisted Medical Interventions Group, DKFZ
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated simpa_documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from simpa.utils import Tags, TISSUE_LIBRARY

from simpa.core.simulation import simulate
from simpa.utils.settings_generator import Settings
from simpa.visualisation.matplotlib_data_visualisation import visualise_data
from simpa.core.device_digital_twins.msot_devices import MSOTAcuityEcho
import numpy as np

from simpa.core.pipeline_components import *

# FIXME temporary workaround for newest Intel architectures
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

# TODO change these paths to the desired executable and save folder
SAVE_PATH = "D:/mcx-tmp-output/"
MCX_BINARY_PATH = "C:/mcx-bin/bin/Release/mcx-exe.exe"     # On Linux systems, the .exe at the end must be omitted.
MATLAB_PATH = "C:/Program Files/MATLAB/R2020b/bin/matlab.exe"
ACOUSTIC_MODEL_SCRIPT = "C:/simpa/simpa/core/acoustic_simulation"

VOLUME_TRANSDUCER_DIM_IN_MM = 75
VOLUME_PLANAR_DIM_IN_MM = 20
VOLUME_HEIGHT_IN_MM = 25
SPACING = 0.25
RANDOM_SEED = 4711

# If VISUALIZE is set to True, the simulation result will be plotted
VISUALIZE = True


def create_example_tissue():
    """
    This is a very simple example script of how to create a tissue definition.
    It contains a muscular background, an epidermis layer on top of the muscles
    and a blood vessel.
    """
    background_dictionary = Settings()
    background_dictionary[Tags.MOLECULE_COMPOSITION] = TISSUE_LIBRARY.muscle()
    background_dictionary[Tags.STRUCTURE_TYPE] = Tags.BACKGROUND

    muscle_dictionary = Settings()
    muscle_dictionary[Tags.PRIORITY] = 1
    muscle_dictionary[Tags.STRUCTURE_START_MM] = [0, 0, 0]
    muscle_dictionary[Tags.STRUCTURE_END_MM] = [0, 0, 100]
    muscle_dictionary[Tags.MOLECULE_COMPOSITION] = TISSUE_LIBRARY.muscle()
    muscle_dictionary[Tags.CONSIDER_PARTIAL_VOLUME] = True
    muscle_dictionary[Tags.ADHERE_TO_DEFORMATION] = True
    muscle_dictionary[Tags.STRUCTURE_TYPE] = Tags.HORIZONTAL_LAYER_STRUCTURE

    vessel_1_dictionary = Settings()
    vessel_1_dictionary[Tags.PRIORITY] = 3
    vessel_1_dictionary[Tags.STRUCTURE_START_MM] = [VOLUME_TRANSDUCER_DIM_IN_MM/2,
                                                    0, 10]
    vessel_1_dictionary[Tags.STRUCTURE_END_MM] = [VOLUME_TRANSDUCER_DIM_IN_MM/2, VOLUME_PLANAR_DIM_IN_MM, 10]
    vessel_1_dictionary[Tags.STRUCTURE_RADIUS_MM] = 3
    vessel_1_dictionary[Tags.MOLECULE_COMPOSITION] = TISSUE_LIBRARY.blood_generic()
    vessel_1_dictionary[Tags.CONSIDER_PARTIAL_VOLUME] = True
    vessel_1_dictionary[Tags.STRUCTURE_TYPE] = Tags.CIRCULAR_TUBULAR_STRUCTURE

    epidermis_dictionary = Settings()
    epidermis_dictionary[Tags.PRIORITY] = 8
    epidermis_dictionary[Tags.STRUCTURE_START_MM] = [0, 0, 0]
    epidermis_dictionary[Tags.STRUCTURE_END_MM] = [0, 0, 1]
    epidermis_dictionary[Tags.MOLECULE_COMPOSITION] = TISSUE_LIBRARY.epidermis()
    epidermis_dictionary[Tags.CONSIDER_PARTIAL_VOLUME] = True
    epidermis_dictionary[Tags.ADHERE_TO_DEFORMATION] = True
    epidermis_dictionary[Tags.STRUCTURE_TYPE] = Tags.HORIZONTAL_LAYER_STRUCTURE

    tissue_dict = Settings()
    tissue_dict[Tags.BACKGROUND] = background_dictionary
    tissue_dict["muscle"] = muscle_dictionary
    tissue_dict["epidermis"] = epidermis_dictionary
    tissue_dict["vessel_1"] = vessel_1_dictionary
    return tissue_dict


def add_msot_specific_settings(settings, volume_creator_key):
    volume_creator_settings = settings[volume_creator_key]
    device = MSOTAcuityEcho()
    probe_size_mm = device.probe_height_mm
    mediprene_layer_height_mm = device.mediprene_membrane_height_mm
    heavy_water_layer_height_mm = probe_size_mm - mediprene_layer_height_mm

    new_volume_height_mm = settings[Tags.DIM_VOLUME_Z_MM] + mediprene_layer_height_mm + \
                           heavy_water_layer_height_mm

    # adjust the z-dim to msot probe height
    settings[Tags.DIM_VOLUME_Z_MM] = new_volume_height_mm

    # adjust the x-dim to msot probe width
    # 1 mm is added (0.5 mm on both sides) to make sure no rounding errors lead to a detector element being outside
    # of the simulated volume.

    if settings[Tags.DIM_VOLUME_X_MM] < round(device.probe_width_mm) + 1:
        width_shift_for_structures_mm = (round(device.probe_width_mm) + 1 - settings[Tags.DIM_VOLUME_X_MM]) / 2
        settings[Tags.DIM_VOLUME_X_MM] = round(device.probe_width_mm) + 1
    else:
        width_shift_for_structures_mm = 0

    for structure_key in volume_creator_settings[Tags.STRUCTURES]:
        device.logger.debug("Adjusting " + str(structure_key))
        structure_dict = volume_creator_settings[Tags.STRUCTURES][structure_key]
        if Tags.STRUCTURE_START_MM in structure_dict:
            structure_dict[Tags.STRUCTURE_START_MM][0] = structure_dict[Tags.STRUCTURE_START_MM][
                                                             0] + width_shift_for_structures_mm
            structure_dict[Tags.STRUCTURE_START_MM][2] = structure_dict[Tags.STRUCTURE_START_MM][
                                                             2] + device.probe_height_mm
        if Tags.STRUCTURE_END_MM in structure_dict:
            structure_dict[Tags.STRUCTURE_END_MM][0] = structure_dict[Tags.STRUCTURE_END_MM][
                                                           0] + width_shift_for_structures_mm
            structure_dict[Tags.STRUCTURE_END_MM][2] = structure_dict[Tags.STRUCTURE_END_MM][
                                                           2] + device.probe_height_mm

    if Tags.US_GEL in volume_creator_settings and volume_creator_settings[Tags.US_GEL]:
        us_gel_thickness = np.random.normal(0.4, 0.1)
        us_gel_layer_settings = Settings({
            Tags.PRIORITY: 5,
            Tags.STRUCTURE_START_MM: [0, 0,
                                      heavy_water_layer_height_mm - us_gel_thickness + mediprene_layer_height_mm],
            Tags.STRUCTURE_END_MM: [0, 0, heavy_water_layer_height_mm + mediprene_layer_height_mm],
            Tags.CONSIDER_PARTIAL_VOLUME: True,
            Tags.MOLECULE_COMPOSITION: TISSUE_LIBRARY.ultrasound_gel(),
            Tags.STRUCTURE_TYPE: Tags.HORIZONTAL_LAYER_STRUCTURE
        })

        volume_creator_settings[Tags.STRUCTURES]["us_gel"] = us_gel_layer_settings
    else:
        us_gel_thickness = 0

    mediprene_layer_settings = Settings({
        Tags.PRIORITY: 5,
        Tags.STRUCTURE_START_MM: [0, 0, heavy_water_layer_height_mm - us_gel_thickness],
        Tags.STRUCTURE_END_MM: [0, 0, heavy_water_layer_height_mm - us_gel_thickness + mediprene_layer_height_mm],
        Tags.CONSIDER_PARTIAL_VOLUME: True,
        Tags.MOLECULE_COMPOSITION: TISSUE_LIBRARY.mediprene(),
        Tags.STRUCTURE_TYPE: Tags.HORIZONTAL_LAYER_STRUCTURE
    })

    volume_creator_settings[Tags.STRUCTURES]["mediprene"] = mediprene_layer_settings

    background_settings = Settings({
        Tags.MOLECULE_COMPOSITION: TISSUE_LIBRARY.heavy_water(),
        Tags.STRUCTURE_TYPE: Tags.BACKGROUND
    })
    volume_creator_settings[Tags.STRUCTURES][Tags.BACKGROUND] = background_settings

# Seed the numpy random configuration prior to creating the global_settings file in
# order to ensure that the same volume
# is generated with the same random seed every time.

np.random.seed(RANDOM_SEED)
VOLUME_NAME = "CompletePipelineTestMSOT_"+str(RANDOM_SEED)

general_settings = {
            # These parameters set the general properties of the simulated volume
            Tags.RANDOM_SEED: RANDOM_SEED,
            Tags.VOLUME_NAME: "CompletePipelineTestMSOT_" + str(RANDOM_SEED),
            Tags.SIMULATION_PATH: SAVE_PATH,
            Tags.SPACING_MM: SPACING,
            Tags.DIM_VOLUME_Z_MM: VOLUME_HEIGHT_IN_MM,
            Tags.DIM_VOLUME_X_MM: VOLUME_TRANSDUCER_DIM_IN_MM,
            Tags.DIM_VOLUME_Y_MM: VOLUME_PLANAR_DIM_IN_MM,
            Tags.VOLUME_CREATOR: Tags.VOLUME_CREATOR_VERSATILE,

            # Simulation Device
            Tags.DIGITAL_DEVICE: Tags.DIGITAL_DEVICE_MSOT,

            # The following parameters set the optical forward model
            Tags.WAVELENGTHS: [700]
        }
settings = Settings(general_settings)
np.random.seed(RANDOM_SEED)

settings['volume_creator'] = {
    Tags.STRUCTURES: create_example_tissue(),
    Tags.SIMULATE_DEFORMED_LAYERS: True
}

settings["optical_model"] = {
    Tags.OPTICAL_MODEL_NUMBER_PHOTONS: 1e7,
    Tags.OPTICAL_MODEL_BINARY_PATH: MCX_BINARY_PATH,
    Tags.ILLUMINATION_TYPE: Tags.ILLUMINATION_TYPE_MSOT_ACUITY_ECHO,
    Tags.LASER_PULSE_ENERGY_IN_MILLIJOULE: 50,
}

settings['acoustic_model'] = {
    Tags.ACOUSTIC_SIMULATION_3D: True,
    Tags.ACOUSTIC_MODEL_BINARY_PATH: MATLAB_PATH,
    Tags.ACOUSTIC_MODEL_SCRIPT_LOCATION: ACOUSTIC_MODEL_SCRIPT,
    Tags.GPU: True,
    Tags.PROPERTY_ALPHA_POWER: 1.05,
    Tags.SENSOR_RECORD: "p",
    Tags.PMLInside: False,
    Tags.PMLSize: [31, 32],
    Tags.PMLAlpha: 1.5,
    Tags.PlotPML: False,
    Tags.RECORDMOVIE: False,
    Tags.MOVIENAME: "visualization_log",
    Tags.ACOUSTIC_LOG_SCALE: True
}

settings['reconstruction_das'] = {
    Tags.RECONSTRUCTION_PERFORM_BANDPASS_FILTERING: False,
    Tags.TUKEY_WINDOW_ALPHA: 0.5,
    Tags.BANDPASS_CUTOFF_LOWPASS: int(8e6),
    Tags.BANDPASS_CUTOFF_HIGHPASS: int(0.1e6),
    Tags.RECONSTRUCTION_BMODE_METHOD: Tags.RECONSTRUCTION_BMODE_METHOD_HILBERT_TRANSFORM,
    Tags.RECONSTRUCTION_APODIZATION_METHOD: Tags.RECONSTRUCTION_APODIZATION_BOX,
    Tags.RECONSTRUCTION_MODE: Tags.RECONSTRUCTION_MODE_PRESSURE
}

settings['reconstruction_tr'] = {
    Tags.ACOUSTIC_SIMULATION_3D: True,
    Tags.GPU: True,
    Tags.PROPERTY_ALPHA_POWER: 1.05,
    Tags.SENSOR_RECORD: "p",
    Tags.PMLInside: False,
    Tags.PMLSize: [31, 32],
    Tags.PMLAlpha: 1.5,
    Tags.PlotPML: False,
    Tags.RECORDMOVIE: False,
    Tags.MOVIENAME: "visualization_log",
    Tags.ACOUSTIC_LOG_SCALE: True,
    Tags.TIME_REVEARSAL_SCRIPT_LOCATION: "C:/simpa/simpa/core/image_reconstruction/",
    Tags.ACOUSTIC_MODEL_BINARY_PATH: MATLAB_PATH
}

settings["noise_initial_pressure"] = {
    Tags.NOISE_MEAN: 1,
    Tags.NOISE_STD: 0.1,
    Tags.NOISE_MODE: Tags.NOISE_MODE_MULTIPLICATIVE,
    Tags.DATA_FIELD: Tags.OPTICAL_MODEL_INITIAL_PRESSURE,
    Tags.NOISE_NON_NEGATIVITY_CONSTRAINT: True
}

settings["noise_time_series"] = {
    Tags.NOISE_STD: 3,
    Tags.NOISE_MODE: Tags.NOISE_MODE_ADDITIVE,
    Tags.DATA_FIELD: Tags.TIME_SERIES_DATA
}

add_msot_specific_settings(settings, "volume_creator")

SIMUATION_PIPELINE = [
    ModelBasedVolumeCreator(settings, "volume_creator"),
    McxComponent(settings, "optical_model"),
    GaussianNoiseModel(settings, "noise_initial_pressure"),
    KwaveAcousticForwardModel(settings, "acoustic_model"),
    GaussianNoiseModel(settings, "noise_time_series"),
    TimeReversalAdapter(settings, "reconstruction_tr")
]

simulate(SIMUATION_PIPELINE, settings)

if Tags.WAVELENGTH in settings:
    WAVELENGTH = settings[Tags.WAVELENGTH]
else:
    WAVELENGTH = 700

if VISUALIZE:
    visualise_data(SAVE_PATH + "/" + VOLUME_NAME + ".hdf5", WAVELENGTH,
                   show_time_series_data=True,
                   show_tissue_density=True,
                   show_reconstructed_data=True,
                   show_fluence=True)
