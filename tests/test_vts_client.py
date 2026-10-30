"""Unit tests for the VTube Studio WebSocket client and booth controller."""
import json
import tempfile
import unittest
from pathlib import Path

from app.core.vts_client import VTSAPIError, VTSClient
from app.core.vts_controller import VTSController


class FakeSocket:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []
        self.closed = False

    def send(self, message):
        self.sent.append(json.loads(message))

    def recv(self):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return json.dumps(response)

    def close(self):
        self.closed = True


def response(request, data, message_type=None):
    return {"requestID": request["requestID"],
            "messageType": message_type or request["messageType"].replace("Request", "Response"),
            "data": data}


class VTSClientTests(unittest.TestCase):
    def make_client(self, responses, root):
        socket = FakeSocket(responses)
        client = VTSClient(token_path=Path(root) / "token.txt",
                           socket_factory=lambda *_a, **_kw: socket)
        return client, socket

    def test_first_authorization_saves_token_and_authenticates(self):
        socket = ScriptedSocket([
            {"data": {"authenticationToken": "secret"}},
            {"data": {"authenticated": True}},
        ])
        client = VTSClient(token_path=Path(self.temp.name) / "token.txt",
                           socket_factory=lambda *_a, **_kw: socket)
        client.connect()
        self.assertEqual((Path(self.temp.name) / "token.txt").read_text(), "secret")
        self.assertFalse(socket.closed)
        client.close()
        self.assertTrue(socket.closed)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_request_reconnects_and_authenticates_again(self):
        token = Path(self.temp.name) / "token.txt"
        token.write_text("ok")
        broken = ScriptedSocket([{"data": {"authenticated": True}}])
        recovered = ScriptedSocket([{"data": {"authenticated": True}},
                                    {"data": {"active": True}}])
        sockets = iter((broken, recovered))
        client = VTSClient(token_path=token, socket_factory=lambda *_a, **_kw: next(sockets))
        client.connect()
        broken.fail_next = OSError("closed")
        self.assertTrue(client.get_api_state()["active"])
        self.assertTrue(broken.closed)
        self.assertEqual([m["messageType"] for m in recovered.sent],
                         ["AuthenticationRequest", "APIStateRequest"])
        client.close()

    def test_api_error_is_exposed(self):
        socket = ScriptedSocket([{"data": {"authenticated": True}},
                                 {"messageType": "APIError",
                                  "data": {"errorID": 401, "message": "denied"}}])
        token = Path(self.temp.name) / "token.txt"
        token.write_text("ok")
        client = VTSClient(token_path=token, socket_factory=lambda *_a, **_kw: socket)
        client.connect()
        with self.assertRaises(VTSAPIError):
            client.get_api_state()

    def test_client_discards_unrelated_responses(self):
        socket = ScriptedSocket([{"data": {"authenticated": True}},
                                 {"requestID": "other", "messageType": "ModelLoadedEvent"},
                                 {"data": {"active": True}}])
        token = Path(self.temp.name) / "token.txt"
        token.write_text("ok")
        client = VTSClient(token_path=token, socket_factory=lambda *_a, **_kw: socket)
        client.connect()
        self.assertTrue(client.get_api_state()["active"])

    def test_available_models_and_load_model_requests(self):
        token = Path(self.temp.name) / "token.txt"
        token.write_text("ok")
        socket = ScriptedSocket([{"data": {"authenticated": True}},
                                 {"data": {"availableModels": [{"modelID": "frog"}]}},
                                 {"data": {"modelID": "frog"}}])
        client = VTSClient(token_path=token, socket_factory=lambda *_a, **_kw: socket)
        self.assertEqual(client.get_available_models()["availableModels"][0]["modelID"], "frog")
        self.assertEqual(client.load_model("frog")["modelID"], "frog")
        self.assertEqual([item["messageType"] for item in socket.sent[-2:]],
                         ["AvailableModelsRequest", "ModelLoadRequest"])
        self.assertEqual(socket.sent[-1]["data"], {"modelID": "frog"})
        with self.assertRaises(ValueError):
            client.load_model("")


class ScriptedSocket(FakeSocket):
    def __init__(self, payloads):
        super().__init__([])
        self.payloads = list(payloads)
        self.last_sent = None
        self.fail_next = None

    def send(self, message):
        self.last_sent = message
        self.sent.append(json.loads(message))

    def recv(self):
        if self.fail_next is not None:
            error, self.fail_next = self.fail_next, None
            raise error
        payload = dict(self.payloads.pop(0))
        request = json.loads(self.last_sent)
        payload.setdefault("requestID", request["requestID"])
        payload.setdefault("messageType", request["messageType"].replace("Request", "Response"))
        return json.dumps(payload)


class VTSControllerTests(unittest.TestCase):
    def test_status_and_hotkey_trigger(self):
        class Client:
            def connect(self): pass
            def get_api_state(self): return {"active": True}
            def get_current_model(self):
                return {"modelLoaded": True, "modelName": "奶蛙", "modelID": "frog"}
            def get_hotkeys(self):
                return {"availableHotkeys": [{"name": "思考", "hotkeyID": "think"}]}
            def trigger_hotkey(self, hotkey_id): return {"hotkeyID": hotkey_id}
            def close(self): pass

        controller = VTSController(Client())
        self.assertEqual(controller.connect()["model_name"], "奶蛙")
        self.assertEqual(controller.hotkeys()[0]["name"], "思考")
        self.assertEqual(controller.trigger("think")["hotkeyID"], "think")
        with self.assertRaises(ValueError):
            controller.trigger("")

    def test_list_and_load_models(self):
        class Client:
            def get_available_models(self):
                return {"availableModels": [{"modelID": "frog", "modelName": "奶蛙", "modelLoaded": True},
                                            {"modelID": "cat", "modelName": "小猫"},
                                            {"modelName": "缺少 ID"}]}
            def load_model(self, model_id):
                return {"modelID": model_id}

        controller = VTSController(Client())
        self.assertEqual(controller.models(), [
            {"model_id": "frog", "model_name": "奶蛙", "model_loaded": True},
            {"model_id": "cat", "model_name": "小猫", "model_loaded": False},
        ])
        self.assertEqual(controller.load_model("cat"), {"modelID": "cat"})
        with self.assertRaises(ValueError):
            controller.load_model("  ")


if __name__ == "__main__":
    unittest.main()
