import logging
from mitmproxy import http

# Import the generation function from our local module
from llm_mock import generate_mock_response

class MockInterceptor:
    """
    mitmproxy addon to intercept outbound HTTP/HTTPS requests,
    prevent them from reaching the internet, and inject a generated mock response.
    """

    async def request(self, flow: http.HTTPFlow) -> None:
        """
        Intercepts the outbound request and generates a fake response.
        mitmproxy's request hook fully supports native python async.
        """
        # 1 & 2. Extract URL, Method, and Request Body
        method: str = flow.request.method
        url: str = flow.request.pretty_url
        
        payload: str = ""
        if flow.request.content:
            try:
                payload = flow.request.content.decode('utf-8')
            except UnicodeDecodeError:
                payload = "<binary content>"

        # 3. Pause the flow and await the response from generate_mock_response
        fake_json_string: str = await generate_mock_response(method, url, payload)

        # 4. Create a new mitmproxy.http.Response.make() object using the injected JSON
        # 5. Assign this fake response to flow.response, short-circuiting the request to the real internet
        flow.response = http.Response.make(
            200,  # OK status code
            fake_json_string.encode('utf-8', errors='replace'),
            {"Content-Type": "application/json"}
        )

        # Log the intercepted URL and the first 100 characters of the fake response to the console
        log_msg = f"Intercepted: {method} {url} -> Mock Response: {fake_json_string[:100]}..."
        logging.info(log_msg)
        print(log_msg)

# Register the addon for mitmproxy
addons = [
    MockInterceptor()
]
