# NetBox configuration for CI only: a throwaway database and dummy keys, never a real installation.
ALLOWED_HOSTS = ["*"]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "netbox",
        "USER": "netbox",
        "PASSWORD": "netbox",
        "HOST": "localhost",
        "PORT": "",
    },
}
REDIS = {
    "tasks": {"HOST": "localhost", "PORT": 6379, "DATABASE": 0, "SSL": False},
    "caching": {"HOST": "localhost", "PORT": 6379, "DATABASE": 1, "SSL": False},
}
SECRET_KEY = "ci-only-not-a-secret-" + "x" * 40
API_TOKEN_PEPPERS = {1: "ci-only-not-a-secret-" + "y" * 40}
