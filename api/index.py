from app import app as flask_app


class _PathFix:
    """Si Vercel reescribe el path a /api/index, se lo saca para que
    Flask vea la ruta original."""

    def __init__(self, wsgi):
        self.wsgi = wsgi

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path == "/api/index" or path.startswith("/api/index/"):
            path = path[len("/api/index"):] or "/"
            environ["PATH_INFO"] = path
        return self.wsgi(environ, start_response)


app = _PathFix(flask_app)
