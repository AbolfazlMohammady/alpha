from axes.backends import AxesStandaloneBackend
from django.contrib.auth.backends import ModelBackend


class BabaeiAxesBackend(AxesStandaloneBackend, ModelBackend):
    """
    BABAEI authentication backend.

    AxesStandaloneBackend is responsible for lockout checks, while
    ModelBackend provides Django's user lookup and permission methods.
    This is important because Django stores the backend path in the
    authenticated session and later calls ``get_user()`` on that backend.
    """

    pass
