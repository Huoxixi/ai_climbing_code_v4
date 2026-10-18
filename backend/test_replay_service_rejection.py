import unittest
import httpx
from core.replay_vision_provider import CompatibleVisionProvider, VisionAPIError


class RejectionTests(unittest.TestCase):
    def test_disconnect_retains_stage_and_type_without_credentials_or_resending(self):
        calls=[]
        def disconnect(request):
            calls.append(request)
            callback=request.extensions['trace']
            callback('http11.send_request_body.complete',{'body':'private input'})
            callback('http11.receive_response_headers.failed',{'exception':'secret-key'})
            raise httpx.RemoteProtocolError('private input secret-key')
        with httpx.Client(transport=httpx.MockTransport(disconnect)) as client:
            with self.assertRaises(VisionAPIError) as caught:
                CompatibleVisionProvider({'base_url':'https://example.invalid','model':'test','api_key':'secret-key'},client)(
                    messages=[],max_tokens=10,cancelled=lambda:False)
        error=caught.exception
        self.assertEqual(len(calls),1)
        self.assertTrue(error.uncertain)
        self.assertEqual(error.diagnostic['exception_type'],'RemoteProtocolError')
        self.assertEqual(error.diagnostic['stages'][-1]['event'],'http11.receive_response_headers.failed')
        self.assertNotIn('secret-key',str(error.diagnostic))
        self.assertNotIn('private input',str(error.diagnostic))

    def test_context_error_is_classified_without_echoing_input_or_retrying(self):
        calls=[]
        def reply(request):
            calls.append(request)
            return httpx.Response(400,json={'error':{'code':'context_length_exceeded',
                'message':'Maximum context length exceeded: secret-key and private echoed input'}})
        client=httpx.Client(transport=httpx.MockTransport(reply))
        with self.assertRaises(VisionAPIError) as caught:
            CompatibleVisionProvider({'base_url':'https://example.invalid/v1','model':'test','api_key':'secret-key'},client)(
                messages=[{'role':'user','content':'private input'}],max_tokens=6000,cancelled=lambda:False)
        error=caught.exception
        self.assertEqual(len(calls),1)
        self.assertFalse(error.uncertain)
        self.assertEqual(error.diagnostic['category'],'context_limit')
        self.assertEqual(error.diagnostic['code'],'context_length_exceeded')
        self.assertNotIn('secret-key',str(error)+str(error.diagnostic))
        self.assertNotIn('private',str(error)+str(error.diagnostic))


if __name__=='__main__':
    unittest.main()
