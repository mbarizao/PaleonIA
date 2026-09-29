import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from paleonia.config import get_settings
from paleonia.desk import create_app
from paleonia.desk_read import _crop, read_page_lines
from paleonia.desk_store import DeskStore, annotate_lines
from paleonia.enhance import crop_dark_border, prepare_for_reading
from paleonia.segment import boxes_from_segmentation
from tests.manuscript_lines import detect_manuscript_lines


def _segment_for_tests(image, **_kwargs):
    return detect_manuscript_lines(image)


_segment_patch = patch("paleonia.desk_store.segment_line_boxes", _segment_for_tests)


def setUpModule():
    _segment_patch.start()


def tearDownModule():
    _segment_patch.stop()


def _page(ys, height=700, width=420, thickness=14):
    image = np.full((height, width, 3), 236, np.uint8)
    for y in ys:
        image[y : y + thickness, 36 : width - 36] = (28, 28, 28)
    return image


def _jpeg(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    if not ok:
        raise RuntimeError("falha ao gravar jpeg")
    return encoded.tobytes()


class SegmentationModelTests(unittest.TestCase):
    def test_boundary_and_baseline_become_document_lines(self):
        segmentation = {
            "lines": [
                {"boundary": [[10, 40], [220, 42], [218, 78], [12, 76]]},
                {"baseline": [[15, 140], [200, 144]]},
            ]
        }
        boxes = boxes_from_segmentation(segmentation, (400, 360, 3))
        self.assertEqual(len(boxes), 2)
        self.assertLess(boxes[0][1], 50)
        self.assertGreater(boxes[0][3], 70)
        self.assertLess(boxes[1][1], 140)
        self.assertGreater(boxes[1][3], 144)
        self.assertLess(boxes[0][1], boxes[1][1])


class ManuscriptLineTests(unittest.TestCase):
    def test_finds_separated_writing_lines(self):
        image = _page([40, 110, 190, 280, 380, 490, 590])
        boxes = detect_manuscript_lines(image)
        self.assertEqual(len(boxes), 7)
        for box, nxt in zip(boxes, boxes[1:]):
            self.assertLessEqual(box[3], nxt[1])
            self.assertGreater(box[2], box[0])
            self.assertLessEqual(box[2], image.shape[1])

    def test_keeps_a_gap_between_close_lines(self):
        image = _page([40, 78], height=220, thickness=16)
        boxes = detect_manuscript_lines(image)
        self.assertEqual(len(boxes), 2)
        self.assertLess(boxes[0][3], boxes[1][1] + 1)

    def test_blank_page_has_no_lines(self):
        image = np.full((400, 300, 3), 242, np.uint8)
        self.assertEqual(detect_manuscript_lines(image), [])

    def test_ruled_spread_keeps_each_written_line(self):
        height, width = 720, 1100
        image = np.full((height, width, 3), 232, np.uint8)
        image[:, 530:555] = 30
        for x0, x1 in ((30, 510), (575, 1070)):
            y = 40
            index = 0
            while y < 680:
                cv2.line(image, (x0, y), (x1, y), (50, 50, 50), 1)
                if index % 2 == 0 and index > 0:
                    for x in range(x0 + 15, x1 - 20, 28):
                        image[y - 14 : y - 2, x : x + 16] = (15, 15, 15)
                y += 32
                index += 1
        boxes = detect_manuscript_lines(image)
        self.assertGreaterEqual(len(boxes), 12)
        self.assertLessEqual(len(boxes), 24)
        self.assertTrue(any((box[0] + box[2]) / 2 < 450 for box in boxes))
        self.assertTrue(any((box[0] + box[2]) / 2 > 700 for box in boxes))
        self.assertTrue(all(box[3] - box[1] < 70 for box in boxes))
        self.assertTrue(all(box[2] - box[0] < 620 for box in boxes))

    def test_lines_survive_uneven_light(self):
        image = np.zeros((520, 400, 3), np.uint8)
        for y in range(520):
            image[y, :] = 70 + int(150 * y / 520)
        for y in (50, 150, 260, 380):
            image[y : y + 12, 28:370] = 25
        boxes = detect_manuscript_lines(image)
        self.assertEqual(len(boxes), 4)


class NumberingTests(unittest.TestCase):
    def test_transcript_numbers_skip_omitted_document_lines(self):
        lines = [
            {
                "id": "a",
                "box": [0, 10, 100, 30],
                "include": True,
                "parts": [{"id": "a1", "text": "um"}, {"id": "a2", "text": "dois"}],
            },
            {
                "id": "b",
                "box": [0, 40, 100, 60],
                "include": False,
                "parts": [{"id": "b1", "text": "fora"}],
            },
            {
                "id": "c",
                "box": [0, 5, 80, 9],
                "include": True,
                "parts": [{"id": "c1", "text": "topo"}],
            },
        ]
        numbered = annotate_lines(lines)
        by_id = {line["id"]: line for line in numbered}
        self.assertEqual(by_id["c"]["linha_documento"], 1)
        self.assertEqual(by_id["c"]["parts"][0]["linha_transcrita"], 1)
        self.assertEqual(by_id["a"]["linha_documento"], 2)
        self.assertEqual([part["linha_transcrita"] for part in by_id["a"]["parts"]], [2, 3])
        self.assertEqual(by_id["b"]["linha_documento"], 3)
        self.assertIsNone(by_id["b"]["parts"][0]["linha_transcrita"])

    def test_open_book_numbers_the_left_page_before_the_right(self):
        def line(line_id, box):
            return {"id": line_id, "box": box, "include": True, "parts": [{"id": line_id + "p", "text": ""}]}

        numbered = annotate_lines(
            [
                line("L2", [10, 200, 400, 230]),
                line("R1", [900, 20, 1300, 50]),
                line("L1", [12, 40, 390, 70]),
                line("R2", [910, 180, 1290, 210]),
            ]
        )
        self.assertEqual([line["id"] for line in numbered], ["L1", "L2", "R1", "R2"])
        self.assertEqual([line["linha_documento"] for line in numbered], [1, 2, 3, 4])


    def test_group_crop_leaves_out_the_line_above(self):
        image = np.full((160, 90, 3), 245, np.uint8)
        image[42:56, 8:80] = (0, 0, 255)
        image[78:94, 8:80] = (0, 180, 0)
        above = {"box": [4, 30, 84, 64]}
        current = {"box": [4, 52, 84, 108]}
        crop = _crop(image, [current], before=above)
        blue = np.all(crop == (0, 0, 255), axis=2).any()
        green = np.all(crop == (0, 180, 0), axis=2).any()
        self.assertFalse(blue)
        self.assertTrue(green)


class ReadingPrepareTests(unittest.TestCase):
    def test_prepare_keeps_size_and_ink(self):
        image = np.full((80, 140, 3), (180, 200, 230), np.uint8)
        image[30:48, 20:110] = (40, 35, 30)
        image[10, 12] = (0, 0, 0)
        prepared = prepare_for_reading(image)
        self.assertEqual(prepared.shape[:2], image.shape[:2])
        self.assertLess(int(prepared[38, 60].max()), 90)
        self.assertGreater(int(prepared[10, 12].min()), 180)

    def test_dark_border_is_cut(self):
        image = np.zeros((60, 90, 3), np.uint8)
        image[8:52, 10:80] = (210, 210, 210)
        image[20:28, 18:70] = (20, 20, 20)
        cropped = crop_dark_border(image, pad=0)
        self.assertLess(cropped.shape[0], image.shape[0])
        self.assertLess(cropped.shape[1], image.shape[1])
        self.assertGreater(int(cropped[0, 0].min()), 100)


class PreparedViewTests(unittest.TestCase):
    def test_existing_page_shows_the_cleaned_image_and_shifts_lines(self):
        image = np.zeros((90, 120, 3), np.uint8)
        image[14:76, 16:104] = (205, 214, 224)
        image[36:48, 28:96] = (25, 25, 25)
        ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        self.assertTrue(ok)
        with tempfile.TemporaryDirectory() as tmp:
            store = DeskStore(tmp)
            (store.images / "p001.jpg").write_bytes(encoded.tobytes())
            store.session["pages"].append(
                {
                    "id": "p001",
                    "filename": "livro.jpg",
                    "width": 120,
                    "height": 90,
                    "sensitivity": 0.55,
                    "lines": [
                        {
                            "id": "ln_borda001",
                            "box": [28, 36, 96, 48],
                            "include": True,
                            "parts": [{"id": "pt_borda001", "text": "linha"}],
                        }
                    ],
                }
            )
            store._save()
            page = store.ensure_prepared("p001")
            self.assertTrue(page["prepared"])
            self.assertLess(page["width"], 120)
            self.assertLess(page["height"], 90)
            self.assertGreater(page["crop_origin"][0], 0)
            self.assertGreater(page["crop_origin"][1], 0)
            shifted = page["lines"][0]["box"]
            self.assertEqual(shifted[0], 28 - page["crop_origin"][0])
            self.assertEqual(shifted[1], 36 - page["crop_origin"][1])
            again = store.ensure_prepared("p001")
            self.assertEqual(again["lines"][0]["box"], shifted)
            self.assertTrue((store.images / "p001.original.jpg").is_file())


@contextmanager
def desk_client(directory):
    with TestClient(create_app(directory)) as client:
        settings = get_settings()
        if settings.auth_password:
            logged = client.post(
                "/api/login",
                json={"username": settings.auth_username, "password": settings.auth_password},
            )
            if logged.status_code != 200:
                raise AssertionError(logged.text)
        yield client


class DeskApiTests(unittest.TestCase):
    def test_import_edit_and_export_keep_both_line_ids(self):
        image = _page([30, 100, 180, 270], height=420, width=380)
        with tempfile.TemporaryDirectory() as tmp:
            with desk_client(tmp) as client:
                uploaded = client.post(
                    "/api/pages",
                    files=[("files", ("folha.jpg", _jpeg(image), "image/jpeg"))],
                )
                self.assertEqual(uploaded.status_code, 200, uploaded.text)
                page = uploaded.json()["pages"][0]
                self.assertGreaterEqual(len(page["lines"]), 3)
                self.assertEqual(page["lines"][0]["linha_documento"], 1)

                lines = page["lines"]
                lines[0]["parts"][0]["text"] = "alpha"
                lines[0]["parts"].append({"id": "pt_extra01", "text": "beta"})
                lines[1]["include"] = False
                lines[2]["parts"][0]["text"] = "gamma"
                saved = client.put(
                    f"/api/pages/{page['id']}",
                    json={"lines": lines, "sensitivity": 0.55},
                )
                self.assertEqual(saved.status_code, 200, saved.text)

                exported = client.get("/api/export.txt")
                self.assertEqual(exported.status_code, 200)
                text = exported.text
                self.assertIn("[T001 | D001 parte 1] alpha", text)
                self.assertIn("[T002 | D001 parte 2] beta", text)
                self.assertIn("beta", text)
                self.assertIn("Fora da transcrição: D002", text)
                self.assertIn("[T003 | D003] gamma", text)
                self.assertNotIn("[T004 | D004]", text)

                document = client.get("/api/export.json").json()
                rows = document["paginas"][0]["linhas"]
                self.assertEqual(rows[0]["linha_transcrita"], 1)
                self.assertEqual(rows[0]["linha_documento"], 1)
                self.assertEqual(rows[1]["linha_documento"], 1)
                self.assertEqual(rows[1]["parte"], 2)
                omitted = document["paginas"][0]["linhas_documento_sem_transcricao"]
                self.assertEqual(omitted[0]["linha_documento"], 2)

                image_response = client.get(page["image_url"])
                self.assertEqual(image_response.status_code, 200)
                self.assertTrue(image_response.content.startswith(b"\xff\xd8"))

    def test_redetect_keeps_text_on_the_same_band(self):
        image = _page([40, 130, 230], height=360, width=360)
        with tempfile.TemporaryDirectory() as tmp:
            store = DeskStore(tmp)
            page = store.add_page("scan.jpg", _jpeg(image))
            self.assertGreaterEqual(len(page["lines"]), 2)
            lines = page["lines"]
            lines[0]["parts"][0]["text"] = "primeira faixa"
            store.replace_lines(page["id"], lines, sensitivity=0.55)
            again = store.redetect(page["id"], 0.55)
            texts = [part["text"] for line in again["lines"] for part in line["parts"]]
            self.assertIn("primeira faixa", texts)

    def test_session_survives_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DeskStore(tmp)
            store.add_page("a.jpg", _jpeg(_page([40, 120], height=240)))
            again = DeskStore(Path(tmp))
            self.assertEqual(len(again.public_session()["pages"]), 1)
            self.assertTrue(again.image_path("p001").is_file())

    def test_automatic_reading_fills_empty_lines_only(self):
        image = _page([40, 120], height=240, width=360)
        with tempfile.TemporaryDirectory() as tmp:
            store = DeskStore(tmp)
            page = store.add_page("folha.jpg", _jpeg(image))
            store.replace_lines(
                page["id"],
                [
                    {
                        "id": "ln_one0001",
                        "box": [20, 30, 300, 70],
                        "include": True,
                        "parts": [{"id": "pt_one0001", "text": ""}],
                    },
                    {
                        "id": "ln_two0002",
                        "box": [20, 100, 300, 140],
                        "include": True,
                        "parts": [{"id": "pt_two0002", "text": "já corrigido"}],
                    },
                ],
            )

            def ask(prompt, crop):
                self.assertIn("1 linha", prompt)
                self.assertGreater(crop.shape[0], 8)
                return {"linhas": ["[sem texto]"]}

            read_page_lines(store, page["id"], ask=ask)
            stored = {line["id"]: line for line in store._require(page["id"])["lines"]}
            self.assertEqual(stored["ln_one0001"]["parts"][0]["text"], "")
            self.assertEqual(stored["ln_two0002"]["parts"][0]["text"], "já corrigido")

            def ask_two(prompt, _crop):
                self.assertIn("2 linhas", prompt)
                return {"linhas": ["alpha", "beta"]}

            read_page_lines(store, page["id"], ask=ask_two, only_empty=False)
            stored = {line["id"]: line for line in store._require(page["id"])["lines"]}
            self.assertEqual(stored["ln_one0001"]["parts"][0]["text"], "alpha")
            self.assertEqual(stored["ln_two0002"]["parts"][0]["text"], "beta")

    def test_transcribe_endpoint_runs_without_blocking(self):
        image = _page([40, 110], height=220, width=320)
        with tempfile.TemporaryDirectory() as tmp:
            with desk_client(tmp) as client:
                uploaded = client.post(
                    "/api/pages",
                    files=[("files", ("folha.jpg", _jpeg(image), "image/jpeg"))],
                )
                page = uploaded.json()["pages"][0]
                line_id = page["lines"][0]["id"]

                def fake(store, page_id, only_empty=True, progress=None):
                    store.set_line_texts(page_id, {line_id: "lido pelo modelo"}, only_empty=only_empty)
                    if progress:
                        progress("Transcrição pronta.", 1, 1)

                with patch("paleonia.desk_read.read_page_lines", fake):
                    started = client.post(f"/api/pages/{page['id']}/transcribe", json={"only_empty": True})
                    self.assertEqual(started.status_code, 200, started.text)
                    self.assertEqual(started.json()["status"], "running")
                    status = {"status": "running"}
                    for _ in range(40):
                        status = client.get(f"/api/pages/{page['id']}/transcribe").json()
                        if status["status"] != "running":
                            break
                        time.sleep(0.05)
                self.assertEqual(status["status"], "done")
                texts = [part["text"] for line in status["page"]["lines"] for part in line["parts"]]
                self.assertIn("lido pelo modelo", texts)


if __name__ == "__main__":
    unittest.main()
