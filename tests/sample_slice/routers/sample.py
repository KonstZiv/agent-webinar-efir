"""Route of the sample slice: gets its adapter by key (tests/test_slices.py)."""

from typing import Annotated

from app.slices.sample import GREETER, Greeter
from fastapi import APIRouter, Depends

from app.adapters.web.dependencies import service

router = APIRouter()

GreeterDep = Annotated[Greeter, Depends(service(GREETER))]


@router.get("/sample")
def sample(greeter: GreeterDep) -> dict[str, str]:
    return {"greeting": greeter.greet()}
