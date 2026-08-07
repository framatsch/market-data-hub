Please change the OAuth callback behavior for the broker authentication (e.g., Schwab/TD Ameritrade) to prevent duplicate application tabs.

**Current Behavior:** 
When the broker redirects back to our application's callback URL after a successful login, the backend redirects the user back to the frontend settings page. Since the login flow was originally opened in a new tab (`window.open(..., '_blank')`), this leaves the user with the application open in two separate tabs.

**Desired Behavior:**
Instead of returning an HTTP Redirect (`302 Found` or `307 Temporary Redirect`) to the settings page, the backend callback endpoint should return a direct HTTP 200 HTML response.

**Implementation Details:**
1. Locate the FastAPI (or equivalent) route that handles the OAuth callback from the broker (the endpoint that receives the `code` and `state`).
2. After successfully exchanging the code for tokens and saving them to the database, remove the redirect to the frontend URL.
3. Instead, return a raw HTML response that simply displays a success message. 

For FastAPI, the implementation should look like this:
```python
from fastapi.responses import HTMLResponse

# inside the callback route:
return HTMLResponse(
    status_code=200,
    content="<h1>Authorization successful. You may close this tab.</h1>"
)
```
4. If there is a failure (e.g., invalid state, missing code, or API error), return a similar HTMLResponse with `status_code=400` and `content="<h1>Authorization failed: <error_details></h1>"`.
