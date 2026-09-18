FROM nousresearch/hermes-agent@sha256:7406def8717ee1be8ca685901166ffadade7c9a2efd6e5f41ae9a38d8606fce1
COPY bootstrap.py /opt/echo/bootstrap.py
COPY home_tools.py /opt/echo/home_tools.py
COPY backend /opt/echo/backend
WORKDIR /opt/data
CMD ["python", "/opt/echo/bootstrap.py"]
