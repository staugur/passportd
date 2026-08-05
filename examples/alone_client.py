# coding:utf-8
"""
Usage: python client.
Access: http://localhost:5000
Warning:
    不要和 OIDC Server 同时使用 127.0.0.1 （不同端口）测试，
    可能会因为 Cookie 覆盖，回调时触发 MismatchingStateError。
"""

from os import getenv

from flask import Flask, url_for, session, request
from flask import render_template_string, redirect
from authlib.integrations.flask_client import OAuth

client_id = getenv("client_id", "")
client_secret = getenv("client_secret", "")
oidc_server_url = "http://127.0.0.1:10030/.well-known/openid-configuration"

app = Flask(__name__)
app.secret_key = "!secret"

oauth = OAuth(app)
oauth.register(
    name="myoidc",
    client_id=client_id,
    client_secret=client_secret,
    server_metadata_url=oidc_server_url,
    client_kwargs={"scope": "openid profile role"},
)


@app.route("/")
def homepage():
    user = session.get("user")
    return render_template_string(
        """
{% if user %}
<pre>
{{ user|tojson(indent=2) }}
</pre>
<a href="/logout">logout</a>
{% else %}
<a href="/login">login</a>
{% endif %}""",
        user=user,
    )


@app.route("/login")
def login():
    redirect_uri = url_for("callback", _external=True)
    return oauth.myoidc.authorize_redirect(redirect_uri)


@app.route("/callback")
def callback():
    err = request.args.get("error")
    if err:
        return f"Error: {err}, description: {request.args.get('error_description')}"
    token = oauth.myoidc.authorize_access_token()
    session["user"] = token["userinfo"]
    return redirect("/")


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
