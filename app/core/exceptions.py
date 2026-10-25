"""Errores de negocio. Los services los lanzan y main.py los convierte en respuestas HTTP,
así la lógica no depende de FastAPI."""


class AppError(Exception):
    status_code = 400

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class NoAutenticado(AppError):
    status_code = 401


class Prohibido(AppError):
    status_code = 403


class NoEncontrado(AppError):
    status_code = 404


class Conflicto(AppError):
    status_code = 409


class ErrorInterno(AppError):
    status_code = 500
