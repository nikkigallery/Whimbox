from dataclasses import dataclass
from whimbox.common.utils.utils import *
from whimbox.common.utils.img_utils import *
from whimbox.common.utils.posi_utils import *
from whimbox.common.logger import logger
from whimbox.map.detection.cvars import *
from whimbox.map.detection.map_assets import *
from whimbox.map.detection.utils import *
import typing as t


@dataclass(slots=True)
class BigMapPrediction:
    """Side-effect-free result shared by navigation and map-mask matching."""

    map_name: str
    resize_scale: float
    center_offset: np.ndarray
    preprocessed: np.ndarray
    result: np.ndarray
    local_maximum: np.ndarray
    selected_result_location: np.ndarray
    position: np.ndarray
    similarity: float
    similarity_local: float


def predict_bigmap(image, map_name: str) -> BigMapPrediction:
    """Match one big-map screenshot without clicking UI or mutating global state."""
    if map_name not in MAP_ASSETS_DICT:
        raise RuntimeError(f"bigmap asset unavailable for {map_name!r}")
    if map_name not in BIGMAP_POSITION_SCALE_DICT:
        raise RuntimeError(f"bigmap scale unavailable for {map_name!r}")

    resize_scale = BIGMAP_POSITION_SCALE_DICT[map_name] * BIGMAP_SEARCH_SCALE
    luma = rgb2luma(image)
    center_offset = (
        np.asarray(image_size(luma), dtype=np.float64) / 2 * resize_scale
    )
    preprocessed = cv2.resize(
        luma,
        None,
        fx=resize_scale,
        fy=resize_scale,
        interpolation=cv2.INTER_NEAREST,
    )

    asset = MAP_ASSETS_DICT[map_name]["luma_0125x"].img
    result = cv2.matchTemplate(asset, preprocessed, cv2.TM_CCOEFF_NORMED)
    _, similarity, _, _ = cv2.minMaxLoc(result)

    local_maximum = cv2.subtract(result, cv2.GaussianBlur(result, (9, 9), 0))
    mask_asset = MAP_ASSETS_DICT[map_name].get("mask_0125x")
    if mask_asset is not None:
        mask = image_center_crop(mask_asset.img, size=image_size(local_maximum))
        local_maximum = cv2.copyTo(local_maximum, mask)
    _, similarity_local, _, selected_location = cv2.minMaxLoc(local_maximum)

    precise_area = area_offset((-4, -4, 4, 4), offset=selected_location)
    precise = crop(
        result,
        AnchorPosi(
            precise_area[0],
            precise_area[1],
            precise_area[2],
            precise_area[3],
        ),
    )
    _, precise_location = cubic_find_maximum(precise, precision=0.05)
    precise_location -= 5
    selected_result_location = (
        np.asarray(selected_location, dtype=np.float64) + precise_location
    )
    position = (
        selected_result_location + center_offset
    ) / BIGMAP_SEARCH_SCALE
    return BigMapPrediction(
        map_name=map_name,
        resize_scale=resize_scale,
        center_offset=center_offset,
        preprocessed=preprocessed,
        result=result,
        local_maximum=local_maximum,
        selected_result_location=selected_result_location,
        position=position,
        similarity=float(similarity),
        similarity_local=float(similarity_local),
    )


class BigMap:

    def __init__(self):
        # Usually to be 0.4~0.5
        self.bigmap_similarity = 0.
        # Usually > 0.05
        self.bigmap_similarity_local = 0.
        # Current position on png
        self.bigmap_position: t.Tuple[float, float] = (0, 0)


    def _predict_bigmap(self, image):
        """
        Args:
            image:

        Returns: (new)png position
        """
        prediction = predict_bigmap(image, self.map_name)
        self.bigmap_similarity = prediction.similarity
        self.bigmap_similarity_local = prediction.similarity_local
        self.bigmap_position = prediction.position

        if CV_DEBUG_MODE:
            cv2.imshow("image", prediction.preprocessed)
            location = prediction.position * BIGMAP_SEARCH_SCALE
            area = AnchorPosi(
                location[0] - 200,
                location[1] - 200,
                location[0] + 200,
                location[1] + 200,
            )
            area = AnchorPosi(area.x1, area.y1, area.x2, area.y2)
            close_area = crop(MAP_ASSETS_DICT[self.map_name]["luma_0125x"].img, area)
            center = (close_area.shape[1] // 2, close_area.shape[0] // 2)
            cv2.circle(close_area, center, 5, (0, 0, 255), 2)
            cv2.imshow("bigmap_nearby", close_area)
            cv2.waitKey(1)


        return prediction.similarity, prediction.position

    def update_bigmap(self, image):
        """
        Get position on bigmap (where you enter from the M button)

        The following attributes will be set:
        - bigmap_similarity
        - bigmap_similarity_local
        - bigmap
        """
        self._predict_bigmap(image)

        logger.trace(
            f'BigMap '
            f'P:({float2str(self.bigmap_position[0], 4)}, {float2str(self.bigmap_position[1], 4)}) '
            f'({float2str(self.bigmap_similarity, 3)}|{float2str(self.bigmap_similarity_local, 3)})'
        )

if __name__ == '__main__':
    CV_DEBUG_MODE = True
    bm = BigMap()
    bm.map_name = MAP_NAME_STARSEA
    from whimbox.interaction.interaction_core import itt
    import time

    while 1:
        bm.update_bigmap(itt.capture())
        print(bm.bigmap_position)
        time.sleep(0.1)
