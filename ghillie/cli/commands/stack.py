"""Stack noun commands for the packaged operator CLI."""

from __future__ import annotations

import typing as typ

from cyclopts import App, Parameter

from ghillie.cli.context import get_current_context
from ghillie.cli.control_plane import ControlPlaneClient
from ghillie.cli.output import render_output
from ghillie.cli.runtime_adapters import select_runtime_adapter

StackProfile = typ.Literal["api-only", "ingestion-worker", "reporting-worker"]
ModelBackend = typ.Literal["mock", "openai"]
RuntimeBackend = typ.Literal["cuprum", "python-api"]

stack_app = App(name="stack", help="Manage the local MVP stack lifecycle.")


@stack_app.command
def up(  # noqa: PLR0913
    *,
    profile: StackProfile = "api-only",
    backend: RuntimeBackend = "cuprum",
    cluster_name: typ.Annotated[
        str, Parameter(env_var="GHILLIE_CLUSTER_NAME")
    ] = "ghillie-local",
    namespace: typ.Annotated[str, Parameter(env_var="GHILLIE_NAMESPACE")] = "ghillie",
    ingress_port: typ.Annotated[
        int | None, Parameter(env_var="GHILLIE_INGRESS_PORT")
    ] = None,
    image: typ.Annotated[str, Parameter(env_var="GHILLIE_IMAGE")] = "ghillie:local",
    provider_github_token_env: str = "GHILLIE_GITHUB_TOKEN",  # noqa: S107
    provider_model_backend: ModelBackend = "mock",
    provider_openai_key_env: str = "GHILLIE_OPENAI_API_KEY",
    background_workers: bool = False,
    wait: bool = True,
) -> str:
    """Start the local stack scaffold without executing real integrations."""
    context = get_current_context()
    adapter = select_runtime_adapter(backend)
    return render_output(
        {
            "noun": "stack",
            "verb": "up",
            "status": "not_implemented",
            "message": "not implemented in Task 2.5.a",
            "backend": adapter.name,
            "profile": profile,
            "cluster_name": cluster_name,
            "namespace": namespace,
            "ingress_port": ingress_port or "auto",
            "image": image,
            "provider_github_token_env": provider_github_token_env,
            "provider_model_backend": provider_model_backend,
            "provider_openai_key_env": provider_openai_key_env,
            "background_workers": background_workers,
            "wait": wait,
            "dry_run": context.config.dry_run,
        },
        output=context.config.output,
    )


@stack_app.command
def down(
    *,
    cluster_name: typ.Annotated[
        str, Parameter(env_var="GHILLIE_CLUSTER_NAME")
    ] = "ghillie-local",
    purge_images: bool = False,
    force: bool = False,
) -> str:
    """Tear down the local stack scaffold."""
    context = get_current_context()
    return render_output(
        {
            "noun": "stack",
            "verb": "down",
            "status": "not_implemented",
            "message": "not implemented in Task 2.5.a",
            "cluster_name": cluster_name,
            "purge_images": purge_images,
            "force": force,
        },
        output=context.config.output,
    )


@stack_app.command
def status(
    *,
    cluster_name: typ.Annotated[
        str, Parameter(env_var="GHILLIE_CLUSTER_NAME")
    ] = "ghillie-local",
    namespace: typ.Annotated[str, Parameter(env_var="GHILLIE_NAMESPACE")] = "ghillie",
) -> str:
    """Show the scaffolded stack status payload."""
    context = get_current_context()
    with ControlPlaneClient(context.config):
        return render_output(
            {
                "noun": "stack",
                "verb": "status",
                "status": "not_implemented",
                "message": "not implemented in Task 2.5.a",
                "cluster_name": cluster_name,
                "namespace": namespace,
                "api_base_url": context.config.api_base_url,
                "api_base_url_source": context.config.api_base_url_source,
            },
            output=context.config.output,
        )


@stack_app.command
def logs(
    *,
    cluster_name: typ.Annotated[
        str, Parameter(env_var="GHILLIE_CLUSTER_NAME")
    ] = "ghillie-local",
    namespace: typ.Annotated[str, Parameter(env_var="GHILLIE_NAMESPACE")] = "ghillie",
    follow: bool = False,
    since: str | None = None,
) -> str:
    """Show the scaffolded stack logs payload."""
    context = get_current_context()
    return render_output(
        {
            "noun": "stack",
            "verb": "logs",
            "status": "not_implemented",
            "message": "not implemented in Task 2.5.a",
            "cluster_name": cluster_name,
            "namespace": namespace,
            "follow": follow,
            "since": since or "all",
        },
        output=context.config.output,
    )
