# SPDX-FileCopyrightText: 2021 Division of Intelligent Medical Systems, DKFZ
# SPDX-FileCopyrightText: 2021 Janek Groehl
# SPDX-License-Identifier: MIT

from simpa.core.simulation_modules.volume_creation_module import VolumeCreatorModuleBase
from simpa.utils import Tags
from simpa.utils.constants import wavelength_dependent_properties
from simpa.io_handling import save_hdf5
import numpy as np
import torch


class SegmentationBasedVolumeCreationAdapter(VolumeCreatorModuleBase):
    """
    This volume creator expects a np.ndarray to be in the settigs
    under the Tags.INPUT_SEGMENTATION_VOLUME tag and uses this array
    together with a SegmentationClass mapping which is a dict defined in
    the settings under Tags.SEGMENTATION_CLASS_MAPPING.

    With this, an even greater utility is warranted.
    """

    def create_simulation_volume(self) -> dict:
        volumes, x_dim_px, y_dim_px, z_dim_px = self.create_empty_volumes()
        wavelength = self.global_settings[Tags.WAVELENGTH]

        segmentation_volume = self.component_settings[Tags.INPUT_SEGMENTATION_VOLUME]
        segmentation_classes = np.unique(segmentation_volume, return_counts=False)
        x_dim_seg_px, y_dim_seg_px, z_dim_seg_px = np.shape(segmentation_volume)

        if x_dim_px != x_dim_seg_px:
            raise ValueError("x_dim of volumes and segmentation must perfectly match but was {} and {}"
                             .format(x_dim_px, x_dim_seg_px))
        if y_dim_px != y_dim_seg_px:
            raise ValueError("y_dim of volumes and segmentation must perfectly match but was {} and {}"
                             .format(y_dim_px, y_dim_seg_px))
        if z_dim_px != z_dim_seg_px:
            raise ValueError("z_dim of volumes and segmentation must perfectly match but was {} and {}"
                             .format(z_dim_px, z_dim_seg_px))

        class_mapping = self.component_settings[Tags.SEGMENTATION_CLASS_MAPPING]

        for seg_class in segmentation_classes:
            class_properties = class_mapping[seg_class].get_properties_for_wavelength(wavelength)
            for volume_key in volumes.keys():
                assigned_prop = class_properties[volume_key]
                if assigned_prop is None:
                    assigned_prop = torch.nan
                volumes[volume_key][segmentation_volume == seg_class] = assigned_prop

        # convert volumes back to CPU
        for key in volumes.keys():
            volumes[key] = volumes[key].cpu().numpy().astype(np.float64, copy=False)

        return volumes
