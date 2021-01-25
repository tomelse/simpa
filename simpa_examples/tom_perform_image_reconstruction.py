# The MIT License (MIT)
#
# Copyright (c) 2018 Computer Assisted Medical Interventions Group, DKFZ
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

from simpa.core.device_digital_twins import DEVICE_MAP
from simpa.io_handling.io_hdf5 import save_hdf5
from simpa.io_handling import load_hdf5
from simpa.utils.settings_generator import Settings
from simpa.utils.dict_path_manager import generate_dict_path
from simpa.utils import Tags
from simpa.core.image_reconstruction.reconstruction_modelling import perform_reconstruction
import matplotlib.pyplot as plt
import numpy as np
import time
import nrrd

WAVELENGTH = 532

settings = Settings()
settings[Tags.WAVELENGTH] = WAVELENGTH
settings[Tags.GPU] = False
settings[Tags.SENSOR_CENTER_FREQUENCY_HZ] = 2e-08
settings[Tags.SPACING_MM] = 0.0001
settings[Tags.MEDIUM_SOUND_SPEED] = 1500
settings[Tags.SIMPA_OUTPUT_PATH] = "my_test_data.hdf5"
settings[
    Tags.RECONSTRUCTION_ALGORITHM] = Tags.RECONSTRUCTION_ALGORITHM_PYTORCH_DAS

acoustic_data_path = generate_dict_path(settings,
                                        Tags.TIME_SERIES_DATA,
                                        wavelength=settings[Tags.WAVELENGTH],
                                        upsampled_data=True)
print(acoustic_data_path)
time_series_data, header = nrrd.read('./test_data.nrrd')

save_hdf5(
    {"testing": True},
    settings[Tags.SIMPA_OUTPUT_PATH])  #initially setup hdf5 file for testing

#save time series data at correct data path
save_hdf5({Tags.TIME_SERIES_DATA: time_series_data},
          settings[Tags.SIMPA_OUTPUT_PATH], acoustic_data_path)

time_series_sensor_data = load_hdf5(settings[Tags.SIMPA_OUTPUT_PATH],
                                    acoustic_data_path)[Tags.TIME_SERIES_DATA]

start = time.time()

perform_reconstruction(settings)

print("Took", time.time() - start, "seconds")

reconstructed_image_path = generate_dict_path(
    settings,
    Tags.RECONSTRUCTED_DATA,
    wavelength=settings[Tags.WAVELENGTH],
    upsampled_data=True)

reconstructed_image = load_hdf5(
    settings[Tags.SIMPA_OUTPUT_PATH],
    reconstructed_image_path)[Tags.RECONSTRUCTED_DATA]

plt.subplot(121)
plt.imshow(time_series_data)
plt.subplot(122)
plt.imshow(reconstructed_image)
plt.show()