from importlib.metadata import PackageNotFoundError, version


try:
    APP_VERSION = version("hospital-marketing-mvp")
except PackageNotFoundError:
    APP_VERSION = "unknown"
