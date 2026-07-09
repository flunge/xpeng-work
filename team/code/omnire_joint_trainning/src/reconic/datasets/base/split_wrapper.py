from typing import List, Tuple

from torch import Generator
from torch.utils.data import IterableDataset, get_worker_info

from ..novel_view_manager import NovelViewManager
from .data_proto import CameraInfo, ImageInfo
from .pixel_source import ScenePixelSource


class IterableSplitWrapper(IterableDataset):
    def __init__(
        self,
        datasource: ScenePixelSource,
        novel_view_manager: NovelViewManager,
        split_indices: List[int],
        split: str = "train",
    ):
        super().__init__()
        self.datasource = datasource
        self.novel_view_manager = novel_view_manager
        self.split_indices = split_indices
        self.split = split

        # TODO (wenkang.qin): resume this state in checkpoint
        # make sure consistency indexes generating in different workers
        self.generator = Generator(device=datasource.device)

    def __getitem__(self, idx) -> Tuple[ImageInfo, CameraInfo]:
        image_info, cam_info = self.datasource.get_image(self.split_indices[idx])
        return image_info, cam_info

    def __len__(self):
        return len(self.split_indices)

    def __iter__(self):
        assert self.split == "train", "Only train splits are iterable."
        num_workers = 1
        worker_id = 0
        worker_info = get_worker_info()
        if worker_info is not None:
            num_workers = worker_info.num_workers
            worker_id = worker_info.id
        while True:
            img_idx = self.datasource.propose_training_image(
                candidate_indices=self.split_indices, num_samples=num_workers, generator=self.generator
            )
            image_info, caemra_info = self.__getitem__(img_idx[worker_id])
            novel_view_image_info, novel_view_caemra_info = self.novel_view_manager.load_novel_view_data(
                image_index=img_idx[worker_id],
                base_image_info=image_info.detach(),
                base_cam_info=caemra_info.detach(),
            )
            if novel_view_image_info is not None and novel_view_caemra_info is not None:
                yield img_idx[worker_id], image_info, caemra_info, novel_view_image_info, novel_view_caemra_info
            else:
                yield img_idx[worker_id], image_info, caemra_info
