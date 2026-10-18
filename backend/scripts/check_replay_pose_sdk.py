"""Check the real pose SDK locally; never read keys or send an API request."""
import io
from pathlib import Path
import socket
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from alibabacloud_facebody20191230.client import Client
    from alibabacloud_facebody20191230.models import BodyPostureAdvanceRequest
    from alibabacloud_tea_util.models import RuntimeOptions
    from core.climb_replay import AliyunReplayAnalyzer

    # Explicit dummy values keep the credential provider away from real keys.
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden in SDK check')):
        analyzer = AliyunReplayAnalyzer(access_key_id='local-sdk-check', access_key_secret='local-sdk-check')
        client = analyzer._client()
        assert isinstance(client, Client)
        assert analyzer._client() is client
        payload = {'Data': {'Outputs': []}}
        with patch.object(client, 'body_posture_advance', return_value=type('Response', (), {'body': payload})()) as request:
            assert analyzer._request_pose(b'local-placeholder') == payload
            request.assert_called_once()
            body, options = request.call_args.args
            assert isinstance(body, BodyPostureAdvanceRequest)
            assert isinstance(body.image_urlobject, io.BytesIO)
            assert body.image_urlobject.getvalue() == b'local-placeholder'
            assert isinstance(options, RuntimeOptions)
    print('Pose SDK import, client initialization and request models passed; no cloud request sent.')


if __name__ == '__main__':
    main()
