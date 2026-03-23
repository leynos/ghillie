"""Stack noun commands for the packaged operator CLI."""

from __future__ import annotations

import typing as typ

from cyclopts import App, Parameter

from ghillie.cli.commands.params import (
    ClusterOptions,
    ModelBackend,
    ProviderOptions,
    RuntimeBackend,
    StackProfile,
    StackRunOptions,
)
from ghillie.cli.context import get_current_context
from ghillie.cli.control_plane import ControlPlaneClient
from ghillie.cli.output import render_output
from ghillie.cli.runtime_adapters import select_runtime_adapter

stack_app = App(name="stack", help="Manage the local MVP stack lifecycle.")


# @codescene(disable:"Excess Number of Function Arguments")
# 2026-03-22: CLI command entry point keeps explicit options for operator UX.
@stack_app.command
def up(  # noqa: PLR0913
    *,
    profile: typ.Annotated[
        StackProfile, Parameter(env_var="GHILLIE_PROFILE")
    ] = StackProfile.API_ONLY,
    backend: typ.Annotated[
        RuntimeBackend, Parameter(env_var="GHILLIE_BACKEND")
    ] = RuntimeBackend.CUPRUM,
    cluster_name: typ.Annotated[
        str, Parameter(env_var="GHILLIE_CLUSTER_NAME")
    ] = "ghillie-local",
    namespace: typ.Annotated[str, Parameter(env_var="GHILLIE_NAMESPACE")] = "ghillie",
    ingress_port: typ.Annotated[
        int | None, Parameter(env_var="GHILLIE_INGRESS_PORT")
    ] = None,
    image: typ.Annotated[str, Parameter(env_var="GHILLIE_IMAGE")] = "ghillie:local",
    provider_github_token_env: str = "GHILLIE_GITHUB_TOKEN",  # noqa: S107
    provider_model_backend: ModelBackend = ModelBackend.MOCK,
    provider_openai_key_env: str = "GHILLIE_OPENAI_API_KEY",
    background_workers: bool = False,
    wait: bool = True,
) -> str:
    """Start the local stack scaffold without executing real integrations."""
    context = get_current_context()
    run_opts = StackRunOptions(
        profile=profile,
        backend=backend,
        background_workers=background_workers,
        wait=wait,
    )
    cluster = ClusterOptions(
        cluster_name=cluster_name,
        namespace=namespace,
        ingress_port=ingress_port,
        image=image,
    )
    provider = ProviderOptions(
        provider_github_token_env=provider_github_token_env,
        provider_model_backend=provider_model_backend,
        provider_openai_key_env=provider_openai_key_env,
    )
    adapter = select_runtime_adapter(run_opts.backend)
    return render_output(
        {
            "noun": "stack",
            "verb": "up",
            "status": "not_implemented",
            "message": "not implemented in Task 2.5.a",
            "backend": adapter.name,
            "profile": run_opts.profile,
            "cluster_name": cluster.cluster_name,
            "namespace": cluster.namespace,
            "ingress_port": cluster.ingress_port or "auto",
            "image": cluster.image,
            "provider_github_token_env": provider.provider_github_token_env,
            "provider_model_backend": provider.provider_model_backend,
            "provider_openai_key_env": provider.provider_openai_key_env,
            "background_workers": run_opts.background_workers,
            "wait": run_opts.wait,
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
