"""
Source url: https://github.com/OPHoperHPO/image-background-remove-tool
Author: Nikita Selin (OPHoperHPO)[https://github.com/OPHoperHPO].
License: Apache License 2.0
"""
import pathlib
from typing import Union, List

import PIL
import numpy as np
import torch
from PIL import Image

from carvekit.ml.arch.basnet.basnet import BASNet
from carvekit.ml.files.models_loc import basnet_pretrained
from carvekit.utils.image_utils import convert_image, load_image
from carvekit.utils.pool_utils import batch_generator, thread_pool_processing

__all__ = ["BASNET"]


class BASNET(BASNet):
    """BASNet model interface"""

    def __init__(self, device='cpu',
                 input_tensor_size: Union[List[int], int] = 320,
                 batch_size: int = 10,
                 load_pretrained: bool = True):
        """
            Initialize the BASNET model

            Args:
                device: processing device
                input_tensor_size: input image size
                batch_size: the number of images that the neural network processes in one run
                load_pretrained: loading pretrained model

        """
        super(BASNET, self).__init__(n_channels=3, n_classes=1)
        self.device = device
        self.batch_size = batch_size
        if isinstance(input_tensor_size, list):
            self.input_image_size = input_tensor_size[:2]
        else:
            self.input_image_size = (input_tensor_size, input_tensor_size)
        self.to(device)
        if load_pretrained:
            self.load_state_dict(torch.load(basnet_pretrained(), map_location=self.device))
        self.eval()

    def data_preprocessing(self, data: PIL.Image.Image) -> torch.Tensor:
        """
            Transform input image to suitable data format for neural network

            Args:
                data: input image

            Returns:
                input for neural network

        """
        resized = data.resize(self.input_image_size)
        # noinspection PyTypeChecker
        resized_arr = np.array(resized, dtype=np.float64)
        temp_image = np.zeros((resized_arr.shape[0], resized_arr.shape[1], 3))
        if np.max(resized_arr) != 0:
            resized_arr /= np.max(resized_arr)
        temp_image[:, :, 0] = (resized_arr[:, :, 0] - 0.485) / 0.229
        temp_image[:, :, 1] = (resized_arr[:, :, 1] - 0.456) / 0.224
        temp_image[:, :, 2] = (resized_arr[:, :, 2] - 0.406) / 0.225
        temp_image = temp_image.transpose((2, 0, 1))
        temp_image = np.expand_dims(temp_image, 0)
        return torch.from_numpy(temp_image).type(torch.FloatTensor)

    @staticmethod
    def data_postprocessing(data: torch.tensor,
                            original_image: PIL.Image.Image) -> PIL.Image.Image:
        """
            Transforms output data from neural network to suitable data
            format for using with other components of this framework.

            Args:
                data: output data from neural network
                original_image: input image which was used for predicted data

            Returns:
                Segmentation mask as PIL Image instance

        """
        data = data.unsqueeze(0)
        mask = data[:, 0, :, :]
        ma = torch.max(mask)  # Normalizes prediction
        mi = torch.min(mask)
        predict = ((mask - mi) / (ma - mi)).squeeze()
        predict_np = predict.cpu().data.numpy() * 255
        mask = Image.fromarray(predict_np).convert("L")
        mask = mask.resize(original_image.size, resample=3)
        mask.save('basnet_mask.png')
        return mask

    def __call__(self, images: List[Union[str, pathlib.Path, PIL.Image.Image]]) -> List[PIL.Image.Image]:
        """
            Passes input images through neural network and returns segmentation masks as PIL.Image.Image instances

            Args:
                images: input images

            Returns:
                segmentation masks as for input images, as PIL.Image.Image instances

        """
        collect_masks = []
        for image_batch in batch_generator(images, self.batch_size):
            images = thread_pool_processing(lambda x: convert_image(load_image(x)), image_batch)
            batches = torch.vstack(thread_pool_processing(self.data_preprocessing, images))
            with torch.no_grad():
                batches = batches.to(self.device)
                masks, d2, d3, d4, d5, d6, d7, d8 = super(BASNET, self).__call__(batches)
                masks_cpu = masks.cpu()
                del d2, d3, d4, d5, d6, d7, d8, batches, masks
            masks = thread_pool_processing(lambda x: self.data_postprocessing(masks_cpu[x], images[x]),
                                           range(len(images)))
            collect_masks += masks
        return collect_masks
