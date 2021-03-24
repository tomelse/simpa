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

from simpa.utils import Tags
from simpa.core.image_reconstruction import ReconstructionAdapterBase
from simpa.io_handling.io_hdf5 import load_data_field
from simpa.core.device_digital_twins import DEVICE_MAP
import numpy as np
import torch


from simpa.utils.settings_generator import Settings
from simpa.process.preprocess_images import normalize, reconstruction_mode_transformation
from simpa.process.signal_processing import get_apodization_factor, bandpass_filtering, apply_b_mode


class PyTorchDASAdapter(ReconstructionAdapterBase):
    def reconstruction_algorithm(self, time_series_sensor_data, settings):
        """
        Applies the Delay and Sum beamforming algorithm [1] to the time series sensor data (2D numpy array where the
        first dimension corresponds to the sensor elements and the second to the recorded time steps) with the given
        beamforming settings (dictionary).
        A reconstructed image (2D numpy array) is returned.
        This implementation uses PyTorch Tensors to perform computations and is able to run on GPUs.

        [1] T. Kirchner et al. 2018, "Signed Real-Time Delay Multiply and Sum Beamforming for Multispectral
        Photoacoustic Imaging", https://doi.org/10.3390/jimaging4100121
        """

        # check for B-mode methods and perform envelope detection on time series data if specified
        if Tags.RECONSTRUCTION_BMODE_BEFORE_RECONSTRUCTION in settings \
                and settings[Tags.RECONSTRUCTION_BMODE_BEFORE_RECONSTRUCTION] \
                and Tags.RECONSTRUCTION_BMODE_METHOD in settings:
            time_series_sensor_data = apply_b_mode(
                time_series_sensor_data, method=settings[Tags.RECONSTRUCTION_BMODE_METHOD])

        ### INPUT CHECKING AND VALIDATION ###
        # check settings dictionary for elements and read them in

        # speed of sound: use given speed of sound, otherwise use average from simulation if specified
        if Tags.PROPERTY_SPEED_OF_SOUND in settings and settings[Tags.PROPERTY_SPEED_OF_SOUND]:
            speed_of_sound_in_m_per_s = settings[Tags.PROPERTY_SPEED_OF_SOUND]
        elif Tags.WAVELENGTH in settings and settings[Tags.WAVELENGTH]:
            sound_speed_m = load_data_field(settings[Tags.SIMPA_OUTPUT_PATH], Tags.PROPERTY_SPEED_OF_SOUND)
            speed_of_sound_in_m_per_s = np.mean(sound_speed_m)
        else:
            raise AttributeError("Please specify a value for PROPERTY_SPEED_OF_SOUND"
                                 "or WAVELENGTH to obtain the average speed of sound")

        # time spacing: use kWave specific dt from simulation if set, otherwise sampling rate if specified,
        if Tags.K_WAVE_SPECIFIC_DT in settings and settings[Tags.K_WAVE_SPECIFIC_DT]:
            time_spacing_in_ms = settings[Tags.K_WAVE_SPECIFIC_DT] * 1000
        elif Tags.SENSOR_SAMPLING_RATE_MHZ in settings and settings[Tags.SENSOR_SAMPLING_RATE_MHZ]:
            time_spacing_in_ms = 1.0 / (settings[Tags.SENSOR_SAMPLING_RATE_MHZ] * 1000)
        else:
            raise AttributeError("Please specify a value for SENSOR_SAMPLING_RATE_MHZ or K_WAVE_SPECIFIC_DT")

        # spacing
        if Tags.SPACING_MM in settings and settings[Tags.SPACING_MM]:
            sensor_spacing_in_mm = settings[Tags.SPACING_MM]
        else:
            raise AttributeError("Please specify a value for SPACING_MM")

        # get device specific sensor positions
        device = DEVICE_MAP[settings[Tags.DIGITAL_DEVICE]]
        device.check_settings_prerequisites(settings)
        device.adjust_simulation_volume_and_settings(settings)

        settings[Tags.DIGITAL_DEVICE_POSITION] = [settings[Tags.DIM_VOLUME_X_MM]/2,
                                                  settings[Tags.DIM_VOLUME_Y_MM]/2,
                                                  device.probe_height_mm]

        sensor_positions = device.get_detector_element_positions_accounting_for_device_position_mm(settings)

        # time series sensor data must be numpy array
        if isinstance(sensor_positions, np.ndarray):
            sensor_positions = torch.from_numpy(sensor_positions)
        if isinstance(time_series_sensor_data, np.ndarray):
            time_series_sensor_data = torch.from_numpy(time_series_sensor_data)
        assert isinstance(time_series_sensor_data,
                          torch.Tensor), 'The time series sensor data must have been converted to a tensor'

        # move tensors to GPU if available, otherwise use CPU
        if Tags.GPU not in settings:
            if torch.cuda.is_available():
                dev = "cuda"
            else:
                dev = "cpu"
        else:
            dev = "cuda" if settings[Tags.GPU] else "cpu"

        device = torch.device(dev)
        sensor_positions = sensor_positions.to(device)
        time_series_sensor_data = time_series_sensor_data.to(device)

        # array must be of correct dimension
        assert time_series_sensor_data.ndim == 2, 'Time series data must have exactly 2 dimensions' \
                                                  ', one for the sensor elements and one for time. ' \
                                                  'Stack images and sensor positions for 3D reconstruction' \
                                                  'Apply beamforming per wavelength if you have a 3D array. '

        # check reconstruction mode - pressure by default
        if Tags.RECONSTRUCTION_MODE in settings:
            mode = settings[Tags.RECONSTRUCTION_MODE]
        else:
            mode = Tags.RECONSTRUCTION_MODE_PRESSURE
        time_series_sensor_data = reconstruction_mode_transformation(time_series_sensor_data, mode=mode, device=device)

        # apply by default bandpass filter using tukey window with alpha=0.5 on time series data in frequency domain
        if Tags.RECONSTRUCTION_PERFORM_BANDPASS_FILTERING not in settings \
                or settings[Tags.RECONSTRUCTION_PERFORM_BANDPASS_FILTERING] is not False:

            cutoff_lowpass = settings[Tags.BANDPASS_CUTOFF_LOWPASS] \
                if Tags.BANDPASS_CUTOFF_LOWPASS in settings else int(8e6)
            cutoff_highpass = settings[Tags.BANDPASS_CUTOFF_HIGHPASS] \
                if Tags.BANDPASS_CUTOFF_HIGHPASS in settings else int(0.1e6)
            tukey_alpha = settings[Tags.TUKEY_WINDOW_ALPHA] if Tags.TUKEY_WINDOW_ALPHA in settings else 0.5
            time_series_sensor_data = bandpass_filtering(time_series_sensor_data,
                                                         time_spacing_in_ms=time_spacing_in_ms,
                                                         cutoff_lowpass=cutoff_lowpass,
                                                         cutoff_highpass=cutoff_highpass,
                                                         tukey_alpha=tukey_alpha,
                                                         device=device)

        ### ALGORITHM ITSELF ###

        ## compute size of beamformed image ##
        xdim = (max(sensor_positions[:, 0]) - min(sensor_positions[:, 0]))/sensor_spacing_in_mm
        xdim = int(xdim) + 1  # correction due to subtraction of indices starting at 0
        ydim = float(time_series_sensor_data.shape[1] * time_spacing_in_ms * speed_of_sound_in_m_per_s) \
            / sensor_spacing_in_mm
        ydim = int(round(ydim))
        zdim = (max(sensor_positions[:, 1]) - min(sensor_positions[:, 1]))/sensor_spacing_in_mm
        zdim = int(zdim) + 1  # correction due to subtraction of indices starting at 0

        n_sensor_elements = sensor_positions.shape[0]

        print(
            f'Number of pixels in X dimension: {xdim}, Y dimension: {ydim}, Z dimension: {zdim},  sensor elements: {n_sensor_elements}')

        # construct output image
        output = torch.zeros((xdim, ydim, zdim), dtype=torch.float32, device=device)

        xx, yy, zz, jj = torch.meshgrid(torch.arange(xdim, device=device),
                                        torch.arange(ydim, device=device),
                                        torch.arange(zdim, device=device),
                                        torch.arange(n_sensor_elements, device=device))

        delays = torch.sqrt(((yy * sensor_spacing_in_mm - sensor_positions[:, 2][jj])) ** 2 +
                            ((xx * sensor_spacing_in_mm - torch.abs(sensor_positions[:, 0][jj]))) ** 2 +
                            ((zz * sensor_spacing_in_mm - torch.abs(sensor_positions[:, 1][jj]))) ** 2) \
            / (speed_of_sound_in_m_per_s * time_spacing_in_ms)

        # perform index validation
        invalid_indices = torch.where(torch.logical_or(delays < 0, delays >= float(time_series_sensor_data.shape[1])))
        torch.clip_(delays, min=0, max=time_series_sensor_data.shape[1] - 1)

        apodization_method = settings[Tags.RECONSTRUCTION_APODIZATION_METHOD] \
            if Tags.RECONSTRUCTION_APODIZATION_METHOD in settings else None
        apodization = get_apodization_factor(apodization_method=apodization_method, dimensions=(xdim, ydim, zdim),
                                             n_sensor_elements=n_sensor_elements, device=device)

        # interpolation of delays
        lower_delays = (torch.floor(delays)).long()
        upper_delays = lower_delays + 1
        torch.clip_(upper_delays, min=0, max=time_series_sensor_data.shape[1] - 1)
        lower_values = time_series_sensor_data[jj, lower_delays]
        upper_values = time_series_sensor_data[jj, upper_delays]
        values = lower_values * (upper_delays - delays) + upper_values * (delays - lower_delays)
        values = values * apodization

        # set values of invalid indices to 0 so that they don't influence the result
        values[invalid_indices] = 0
        sum = torch.sum(values, dim=3)
        counter = torch.count_nonzero(values, dim=3)
        torch.divide(sum, counter, out=output)

        reconstructed = np.flipud(output.cpu().numpy())

        # check for B-mode methods and perform envelope detection on beamformed image if specified
        if Tags.RECONSTRUCTION_BMODE_AFTER_RECONSTRUCTION in settings \
                and settings[Tags.RECONSTRUCTION_BMODE_AFTER_RECONSTRUCTION] \
                and Tags.RECONSTRUCTION_BMODE_METHOD in settings:
            reconstructed = apply_b_mode(reconstructed, method=settings[Tags.RECONSTRUCTION_BMODE_METHOD])

        return normalize(reconstructed)


def reconstruct_DAS_PyTorch(time_series_sensor_data: np.ndarray, settings: dict = None, sound_of_speed: int = 1540,
                            time_spacing: float = 2.5e-8, sensor_spacing: float = 0.1) -> np.ndarray:
    """
    Convenience function for reconstructing time series data using Delay and Sum algorithm implemented in PyTorch

    :param time_series_sensor_data: (2D numpy array) sensor data of shape (sensor elements, time steps)
    :param settings: (dict) settings dictionary: by default there is none and the other parameters are used instead,
                     but if parameters are given in the settings those will be used instead of parsed arguments)
    :param sound_of_speed: (int) speed of sound in medium in meters per second (default: 1540 m/s)
    :param time_spacing: (float) time between sampling points in seconds (default: 2.5e-8 s which is equal to 40 MHz)
    :param sensor_spacing: (float) space between sensor elements in millimeters (default: 0.1 mm)
    :return: (2D numpy array) reconstructed image as 2D numpy array
    """

    # create settings if they don't exist yet
    if settings is None:
        settings = Settings()

    # parse reconstruction settings if they are not given in the settings
    if Tags.PROPERTY_SPEED_OF_SOUND not in settings or settings[Tags.PROPERTY_SPEED_OF_SOUND] is None:
        settings[Tags.PROPERTY_SPEED_OF_SOUND] = sound_of_speed

    if Tags.SENSOR_SAMPLING_RATE_MHZ not in settings or settings[Tags.SENSOR_SAMPLING_RATE_MHZ] is None:
        settings[Tags.SENSOR_SAMPLING_RATE_MHZ] = (1.0 / time_spacing) / 1000000

    if Tags.SPACING_MM not in settings or settings[Tags.SPACING_MM] is None:
        settings[Tags.SPACING_MM] = sensor_spacing

    adapter = PyTorchDASAdapter()
    return adapter.reconstruction_algorithm(time_series_sensor_data, settings)
