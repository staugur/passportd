from os import getenv

from flask import Flask, redirect, session, render_template_string
from flask_pluginkit import PluginManager

app = Flask(__name__)
app.secret_key = getenv("SECRET_KEY", "dev-secret-change-me")

app.config.update(
    PASSPORTD_OIDC_CLIENT_ID=getenv(
        "PASSPORTD_OIDC_CLIENT_ID",
        "LitzywCR8H1dmpxieKJp2nag",
    ),
    PASSPORTD_OIDC_CLIENT_SECRET=getenv(
        "PASSPORTD_OIDC_CLIENT_SECRET",
        "ysSUqMYsf9LDdEm6UpDn6nBhElNEMd9MCV3v85keooPz6nyG",
    ),
    PASSPORTD_OIDC_SERVER_METADATA_URL=getenv(
        "PASSPORTD_OIDC_SERVER_METADATA_URL",
        "https://passport.saintic.com/.well-known/openid-configuration",
    ),
)

PluginManager(app, plugin_packages=["flask_pluginkit_oidc"])


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
<a href="{{ url_for('oidc.login') }}">login</a>
{% endif %}""",
        user=user,
    )


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")


if __name__ == "__main__":
    app.run(debug=True)
