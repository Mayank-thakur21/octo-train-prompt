"""Built-in templates and template rendering."""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import AuthFirstRoute, StateDep, guard
from app.errors import missing_variables
from app.schemas import RenderRequest, RenderResult, TemplatesResponse, VariableInfoOut
from app.services import templating
from app.services.validation import check_template, check_variables

router = APIRouter(prefix="/api", route_class=AuthFirstRoute, tags=["templates"])


@router.get("/templates", response_model=TemplatesResponse, dependencies=[guard("default")])
async def list_templates() -> TemplatesResponse:
    """The built-in starter templates."""
    return TemplatesResponse.model_validate(
        {"templates": [template.as_dict() for template in templating.BUILTIN_TEMPLATES]}
    )


@router.post("/templates/render", response_model=RenderResult, dependencies=[guard("tokens")])
async def render_template(body: RenderRequest, state: StateDep) -> RenderResult:
    """Render system and prompt; strict mode rejects missing variables."""
    check_template(state.settings, system=body.system, prompt=body.prompt)
    check_variables(state.settings, body.variables)
    rendered = templating.render(body.system, body.prompt, body.variables)
    if body.strict and rendered.missing:
        raise missing_variables(rendered.missing)
    return RenderResult(
        system=rendered.system,
        prompt=rendered.prompt,
        variables=[VariableInfoOut(**info.as_dict()) for info in rendered.variables],
        missing=rendered.missing,
    )
