from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from whimbox.map.mask.models import MapMaskPoint
from whimbox.map.mask.pearpal_auth import PearPalCredentials, PearPalUserClient
from whimbox.map.mask.pearpal_provider import OfficialPearPalProvider, _parse_spawner_detail
from whimbox.map.mask.service import MapMaskService


class PearPalPointDetailTests(unittest.TestCase):
    def test_detail_parser_extracts_text_and_safe_images(self):
        detail = _parse_spawner_detail(
            {
                "description": json.dumps([
                    {"lang": "zh-cn", "text": "花愿镇11号"},
                    {"lang": "en", "text": "Florawish No.11"},
                ]),
                "creator_post": {
                    "content": "从屋顶跳至二楼阳台获得。",
                    "difficulty": 2,
                    "role_name": "测试贡献者",
                    "images": [
                        {"origin": "https://material.papegames.com/image.jpeg"},
                        {"origin": "javascript:alert(1)"},
                        {"origin": "https://example.com/image.jpeg"},
                    ],
                },
            },
            "zh-cn",
        )
        self.assertEqual(detail["location_description"], "花愿镇11号")
        self.assertEqual(detail["content"], "从屋顶跳至二楼阳台获得。")
        self.assertEqual(detail["difficulty"], 2)
        self.assertEqual(detail["images"], ["https://material.papegames.com/image.jpeg"])

    def test_client_uses_region_client_id_and_authenticated_payload(self):
        client = PearPalUserClient(region="oversea")
        response = Mock()
        response.geturl.return_value = client.spawner_info_url
        response.headers = {}
        response.read.return_value = b'{"code":0,"data":{"id":1360}}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        credentials = PearPalCredentials(token="example-token", openid="12345")
        with patch("urllib.request.urlopen", return_value=response) as open_url:
            self.assertEqual(client.fetch_spawner_detail("1360", credentials)["id"], 1360)
        request = open_url.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(body, {
            "client_id": 1116,
            "id": 1360,
            "token": "example-token",
            "openid": "12345",
        })

    def test_provider_fetches_only_when_clicked_and_caches_detail(self):
        user_client = Mock()
        user_client.fetch_spawner_detail.return_value = {
            "description": "[]",
            "creator_post": {"content": "到屋顶获得", "images": []},
        }
        provider = OfficialPearPalProvider(
            enabled=True,
            client=Mock(),
            user_client=user_client,
            background=False,
        )
        point = MapMaskPoint(
            id="pearpal:1360",
            label_id="pearpal_box",
            name="宝箱",
            map_name="miraland",
            image_x=10,
            image_y=20,
            detail={"source_id": "1360"},
        )
        provider._load_state = "ready"
        provider._point_by_id = {point.id: point}
        self.assertEqual(provider.get_point_detail(point.id)["detail"]["content"], "到屋顶获得")
        provider.get_point_detail(point.id)
        user_client.fetch_spawner_detail.assert_called_once_with("1360", None)

    def test_click_notification_uses_game_client_coordinates(self):
        service = MapMaskService()
        notify = Mock()
        with (
            patch.object(service, "_should_block_mouse_wheel", return_value=True),
            patch("whimbox.map.mask.service.HANDLE_OBJ.get_window_rect", return_value=(100, 200, 1000, 600)),
            patch.dict("sys.modules", {"whimbox.rpc_server": SimpleNamespace(notify_event=notify)}),
        ):
            service._notify_bigmap_click(600, 500)
            service._notify_bigmap_click(99, 500)
        notify.assert_called_once_with(
            "event.map_mask.bigmap_click",
            {"relative_x": 0.5, "relative_y": 0.5},
        )


if __name__ == "__main__":
    unittest.main()
