import time
import typing as t
import cv2

from whimbox.map.detection.utils import *
from whimbox.interaction.interaction_core import itt
from whimbox.common.timer_module import Timer
from whimbox.common.utils.posi_utils import *
from whimbox.map.detection.map_assets import *
from whimbox.common.utils.utils import *

class MiniMap:
    def __init__(self):
        # Usually to be 0.4~0.5
        self.position_similarity = 0.
        self.position_sample_time = 0.0
        # Usually > 0.05
        self.position_similarity_local = 0.
        # Current position on png
        self.position: t.Tuple[float, float] = (0, 0)

        # Usually to be 0.90~0.98
        # Warnnings will be logged if similarity <= 0.8
        self.direction_similarity = 0.
        # Current character direction with an error of about 0.1 degree
        self.direction: float = 0.

        # The bigger the better
        self.rotation_confidence = 0.
        # Current cameta rotation with an error of about 0.001 degree
        self.rotation: float = 0

        self.pos_change_timer = Timer(diff_start_time=30)

    def init_position(self, position: t.Tuple[int, int]):
        self.position = position
        self.position_sample_time = 0.0

    def _get_minimap(self, image, radius):
        area = area_offset((-radius, -radius, radius, radius), offset=MINIMAP_CENTER)
        area = AnchorPosi(area[0], area[1], area[2], area[3], anchor=ANCHOR_TOP_LEFT)
        image = crop(image, area)
        return image


    def _predict_position(self, image, scale):
        """
        Args:
            image:
            scale:

        Returns:
            float: Precise similarity
            float: local_sim
            tuple[float, float]: Location on png
        """
        scale *= POSITION_SEARCH_SCALE
        local = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        mask = cv2.resize(MiniMapMask, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        if CV_DEBUG_MODE:
            local_copy = local.copy()
            local_copy[mask == 0] = 0
            cv2.imshow('local', local_copy)
            cv2.waitKey(1)
        # Product search area
        search_position = np.array(self.position, dtype=np.int64)
        search_size = np.array(image_size(local)) * POSITION_SEARCH_RADIUS
        search_size = (search_size // 2 * 2).astype(np.int64)
        search_area = area_offset((0, 0, *search_size), offset=(-search_size // 2).astype(np.int64))
        search_area = area_offset(search_area, offset=np.multiply(search_position, POSITION_SEARCH_SCALE))
        search_area = np.array(search_area).astype(np.int64)
        search_area = AnchorPosi(search_area[0], search_area[1], search_area[2], search_area[3])
        search_image = crop(MAP_ASSETS_DICT[self.map_name]['luma_05x'].img, search_area)
        if CV_DEBUG_MODE:
            show_search_image = search_image.copy()
            # 在show_search_image中心画一个半径为2px的方块
            h, w = show_search_image.shape[:2]
            cx, cy = w // 2, h // 2
            # 方块边界
            x1, y1 = max(cx - 2, 0), max(cy - 2, 0)
            x2, y2 = min(cx + 2, w - 1), min(cy + 2, h - 1)
            # 画方块
            show_search_image[y1:y2+1, x1:x2+1] = 255
            cv2.imshow('search_image', show_search_image)
            cv2.waitKey(1)

        result = cv2.matchTemplate(search_image, local, cv2.TM_CCOEFF_NORMED, mask=mask)
        _, sim, _, loca = cv2.minMaxLoc(result)

        # Gaussian filter to get local maximum
        local_maximum = cv2.subtract(result, cv2.GaussianBlur(result, (5, 5), 0))
        _, local_sim, _, loca = cv2.minMaxLoc(local_maximum)

        # Calculate the precise location using CUBIC
        area = area_offset((-4, -4, 4, 4), offset=loca)
        area = AnchorPosi(area[0], area[1], area[2], area[3])
        precise = crop(result, area)
        precise_sim, precise_loca = cubic_find_maximum(precise, precision=0.05)
        precise_loca -= 5

        # Location on search_image
        lookup_loca = precise_loca + loca + np.array(image_size(image)) * scale / 2
        # Location on png
        global_loca = (lookup_loca + [search_area.x1, search_area.y1]) / POSITION_SEARCH_SCALE
        # Can't figure out why but the result_of_0.5_lookup_scale + 0.5 ~= result_of_1.0_lookup_scale
        global_loca += POSITION_MOVE
        return precise_sim, local_sim, global_loca


    def update_position(self, origin_image):
        """
        Get position on png

        The following attributes will be set:
        - position_similarity
        - position
        """
        if self.map_name == MAP_NAME_UNSUPPORTED:
            self.position = (0, 0)
            return self.position
            
        image = self._get_minimap(origin_image, MINIMAP_POSITION_RADIUS)
        image = rgb2luma(image)

        best_sim, best_local_sim, best_loca = self._predict_position(image, MINIMAP_POSITION_SCALE_DICT[self.map_name])

        if self.verify_position(tuple(np.round(best_loca, 1))):
            self.position_similarity = round(best_sim, 5)
            self.position_similarity_local = round(best_local_sim, 5)
            self.position = tuple(np.round(best_loca, 1))
            self.position_sample_time = time.monotonic()
        return self.position


    def verify_position(self, pos):
        dt = self.pos_change_timer.get_diff_time()
        if dt > 20:
            self.pos_change_timer.reset()
            return True
        else:
            if euclidean_distance(pos, self.position) >= MOVE_SPEED * dt + 1:
                logger.warning(f'position change above limit: {euclidean_distance(pos, self.position)} >= {MOVE_SPEED * dt + 1}. result will be abandon.')
                return False
            else:
                self.pos_change_timer.reset()
                return True


    def update_direction(self, image):
        """
        Get direction of character

        The following attributes will be set:
        - direction_similarity
        - direction
        """
        image = self._get_minimap(image, DIRECTION_RADIUS)
        image = color_similarity_2d(image, color=DIRECTION_SIMILARITY_COLOR)
        try:
            area = area_pad(get_bbox(image, threshold=128), pad=-1)
            area = AnchorPosi(area[0], area[1], area[2], area[3])
        except IndexError:
            # IndexError: index 0 is out of bounds for axis 0 with size 0
            logger.warning('No direction arrow on minimap')
            return
        image = crop(image, area=area)
        if CV_DEBUG_MODE:
            cv2.imshow('direction_image', image)
            cv2.waitKey(1)

        scale = DIRECTION_ROTATION_SCALE * DIRECTION_SEARCH_SCALE
        mapping = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        result = cv2.matchTemplate(ArrowRotateMap.img, mapping, cv2.TM_CCOEFF_NORMED)
        result = cv2.subtract(result, cv2.GaussianBlur(result, (5, 5), 0))
        _, sim, _, loca = cv2.minMaxLoc(result)
        loca = np.array(loca) / DIRECTION_SEARCH_SCALE // (DIRECTION_RADIUS * 2)
        degree = int((loca[0] + loca[1] * 8) * 5)

        def to_map(x):
            return int((x * DIRECTION_RADIUS * 2 + DIRECTION_RADIUS) * POSITION_SEARCH_SCALE)

        # Row on ArrowRotateMapAll
        row = int(degree // 8) + 45
        # Calculate +-1 rows to get result with a precision of 1
        row = (row - 2, row + 3)
        # Convert to ArrowRotateMapAll and to be 5px larger
        row = (to_map(row[0]) - 5, to_map(row[1]) + 5)

        precise_map = ArrowRotateMapAll.img[row[0]:row[1], :]
        result = cv2.matchTemplate(precise_map, mapping, cv2.TM_CCOEFF_NORMED)
        result = cv2.subtract(result, cv2.GaussianBlur(result, (5, 5), 0))

        def to_map(x):
            return int((x * DIRECTION_RADIUS * 2) * POSITION_SEARCH_SCALE)

        def get_precise_sim(d):
            y, x = divmod(d, 8)
            im = result[to_map(y):to_map(y + 1), to_map(x):to_map(x + 1)]
            _, sim, _, _ = cv2.minMaxLoc(im)
            return sim

        precise = np.array([[get_precise_sim(_) for _ in range(24)]])
        precise_sim, precise_loca = cubic_find_maximum(precise, precision=0.1)
        precise_loca = degree // 8 * 8 - 8 + precise_loca[0]

        self.direction_similarity = round(precise_sim, 3)
        self.direction = precise_loca % 360
        # Convert
        if self.direction > 180:
            self.direction = 360 - self.direction
        else:
            self.direction = -self.direction
        return self.direction

    def _get_minimap_subtract(self, image, update_position=True):
        """
        Subtract the corresponding background from the current minimap
        to obtain the white translucent area of camera rotation

        Args:
            image:
            update_position (bool): False to reuse position result

        Returns:
            np.ndarray
        """
        if update_position:
            self.update_position(image)

        # Get current minimap
        scale = MINIMAP_POSITION_SCALE_DICT[self.map_name] * POSITION_SEARCH_SCALE
        minimap = self._get_minimap(image, radius=MINIMAP_RADIUS)
        minimap = rgb2luma(minimap)

        radius = MINIMAP_RADIUS * scale
        area = area_offset((-radius, -radius, radius, radius),
                           offset=np.array(self.position) * POSITION_SEARCH_SCALE)
        # Search 15% larger
        area = area_pad(area, pad=-int(radius * 0.15))
        area = np.array(area).astype(int)
        area = AnchorPosi(area[0], area[1], area[2], area[3])

        # Crop pngmap around current position and resize to current minimap
        image = crop(MAP_ASSETS_DICT[self.map_name]['luma_05x'].img, area)
        image = cv2.resize(image, None, fx=1 / scale, fy=1 / scale, interpolation=cv2.INTER_LINEAR)
        # if CV_DEBUG_MODE:
        #     cv2.imshow('minimap', minimap)
        #     cv2.waitKey(1)
        #     cv2.imshow('map_image', image)
        #     cv2.waitKey(1)
        # Search best match
        result = cv2.matchTemplate(image, minimap, cv2.TM_CCOEFF_NORMED)
        sim, loca = cubic_find_maximum(result, precision=0.05)
        # Re-crop the pngmap that best match current map
        area = (0, 0, MINIMAP_RADIUS * 2, MINIMAP_RADIUS * 2)
        src = area2corner(area_offset(area, loca)).astype(np.float32)
        dst = area2corner(area).astype(np.float32)
        homo = cv2.getPerspectiveTransform(src, dst)
        image = cv2.warpPerspective(image, homo, area[2:], flags=cv2.INTER_LINEAR)

        # current - background
        minimap = minimap.astype(float)
        image = image.astype(float)
        image = (255 - image) / (255 - minimap + 0.1) * 64
        image = cv2.min(cv2.max(image, 0), 255)
        image = image.astype(np.uint8)
        return image

    def _predict_rotation(self, image):
        '''具体原理：https://www.bilibili.com/video/BV1A84y1A7ku'''
        d = MINIMAP_RADIUS * 2
        # Upscale image and apply Gaussian filter for smother results
        scale = 2
        image = cv2.GaussianBlur(image, (3, 3), 0)
        # Expand circle into rectangle
        remap = cv2.remap(image, *RotationRemapTable, cv2.INTER_LINEAR)[d * 2 // 10:d * 7 // 10].astype(
            np.float32)
        remap = cv2.resize(remap, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
        # Find derivative
        gradx = cv2.Scharr(remap, cv2.CV_32F, 1, 0)
        if CV_DEBUG_MODE:
            # 将gradx转换为适合显示的格式(0-255的uint8类型)
            gradx_display = cv2.normalize(gradx, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
            cv2.imshow('gradx', gradx_display)
            cv2.waitKey(1)

        # Magic parameters for scipy.find_peaks
        para = {
            'height': 150,
            'wlen': d * scale,
        }

        # `l` for the left of sight area, derivative is positive
        # `r` for the right of sight area, derivative is negative
        l = np.bincount(signal.find_peaks(gradx.ravel(), **para)[0] % (d * scale), minlength=d * scale)
        r = np.bincount(signal.find_peaks(-gradx.ravel(), **para)[0] % (d * scale), minlength=d * scale)
        l, r = np.maximum(l - r, 0), np.maximum(r - l, 0)

        conv0 = []
        kernel = 2 * scale
        for offset in range(-kernel + 1, kernel):
            result = l * convolve(np.roll(r, -d * scale // 4 + offset), kernel=3 * scale)
            minus = l * convolve(np.roll(r, offset), kernel=10 * scale) // 5
            result -= minus
            result = convolve(result, kernel=3 * scale)
            conv0 += [result]

        conv0 = np.array(conv0)
        conv0[conv0 < 1] = 1
        maximum = np.max(conv0, axis=0)
        if peak_confidence(maximum) > 0.3:
            # Good match
            result = maximum
        else:
            # Convolve again to reduce noice
            average = np.mean(conv0, axis=0)
            minimum = np.min(conv0, axis=0)
            result = convolve(maximum * average * minimum, 2 * scale)

        # Convert match point to degree
        self.degree = np.argmax(result) / (d * scale) * 2 * np.pi + np.pi / 4
        degree = np.argmax(result) / (d * scale) * 360 + 135
        degree = round(degree % 360, 3)
        self.rotation = degree

        # Convert
        if degree > 180:
            degree = 360 - degree
        else:
            degree = -degree
        self.rotation = degree

        # Calculate confidence
        # A flat response contains no camera direction, even if the peak
        # confidence helper reports 1.0 for a signal with zero peaks.
        self.rotation_confidence = round(peak_confidence(result), 3) if np.ptp(result) > 0 else 0.0
        return degree


    def update_rotation(self, image, update_position=True):
        minimap = self._get_minimap_subtract(image, update_position=update_position)
        self.rotation = self._predict_rotation(minimap)
        if CV_DEBUG_MODE:
            self.show_rotation(minimap, self.degree)
        return self.rotation


    def show_rotation(self, img, ang):
        if ang is not None:
            img = cv2.line(img, (img.shape[0] // 2, img.shape[0] // 2),
                           (int(img.shape[0] // 2 + 1000 * np.cos(ang)), int(img.shape[0] // 2 + 1000 * np.sin(ang))),
                           (255, 255, 0), 2)
        cv2.imshow('result', img)
        cv2.waitKey(1)


    def update_minimap(self, image):
        """
        Args:
            image:
        """
        self.update_position(image)
        self.update_direction(image)
        self.update_rotation(image, update_position=False)
        self.minimap_print_log()


    def minimap_print_log(self):
        logger.trace(
            f'MiniMap '
            f'P:({float2str(self.position[0], 4)}, {float2str(self.position[1], 4)}) '
            f'({float2str(self.position_similarity, 3)}|{float2str(self.position_similarity_local, 3)}), '
            f'D:{float2str(self.direction, 3)} ({float2str(self.direction_similarity, 3)}), '
            f'R:{self.rotation} ({float2str(self.rotation_confidence)})')


    def is_position_near(self, position, threshold=1) -> bool:
        diff = np.linalg.norm(np.subtract(position, self.position))
        return diff <= threshold

    def is_direction_near(self, direction, threshold=10) -> bool:
        diff = (self.direction - direction) % 360
        return diff <= threshold or diff >= 360 - threshold

    def is_rotation_near(self, rotation, threshold=10) -> bool:
        diff = (self.rotation - rotation) % 360
        return diff <= threshold or diff >= 360 - threshold


if __name__ == '__main__':
    """
    MiniMap windows窗口监听测试
    """
    import time
    from whimbox.map.convert import convert_GameLoc_to_PngMapPx
    minimap = MiniMap()
    # minimap.map_name = MAP_NAME_MIRALAND
    # minimap.init_position((2800*2, 3920*2)) # 疯愿之子营地
    # minimap.init_position((3213*2, 2203*2)) # 花愿镇，搭配师协会
    # minimap.init_position(convert_GameLoc_to_PngMapPx((-13351.5, -41940), MAP_NAME_MIRALAND))
    # minimap.init_position((5650.7, 4531.5)) # 蓝龙
    # minimap.map_name = MAP_NAME_STARSEA
    # minimap.init_position((3087.6,2260.0)) # 海滩
    # minimap.init_position((2030.8, 1394.4)) # 晶簇之谷
    minimap.map_name = MAP_NAME_HOME
    minimap.init_position(convert_GameLoc_to_PngMapPx((4724.2218449652, 9033.282368272), MAP_NAME_HOME))

    CV_DEBUG_MODE = True
    # 定位测试
    if True:
        while 1:
            time.sleep(0.1)
            minimap.update_position(itt.capture())
            print(minimap.position)

    # 镜头朝向测试
    if False:
        while 1:
            time.sleep(0.1)
            minimap.update_rotation(itt.capture(), update_position=True)
            print(minimap.rotation)
            # minimap.show_rotation(minimap.rotation)

    # 人物朝向测试
    if False:
        while 1:
            time.sleep(0.1)
            minimap.update_direction(itt.capture())
            print(minimap.direction)

    # 完整测试
    if False:
        # 你可以移动人物，GIA会持续监听小地图位置和角色朝向
        while 1:
            image = itt.capture()
            # image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            # if image.shape != (1080, 1920, 3):
            #     time.sleep(0.3)
            #     continue
            minimap.update_minimap(image)
            # minimap.position_benchmark()
            time.sleep(0.1)



