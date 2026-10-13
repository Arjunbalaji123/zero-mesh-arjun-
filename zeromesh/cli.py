"""
ZeroMesh CLI — Command Line Interface
======================================
Commands:
  zeromesh start       Start a ZeroMesh peer node with REST API
  zeromesh upload      Upload and distribute a local file
  zeromesh download    Download and reassemble a file by manifest ID
  zeromesh list-files  List all files tracked by local node
  zeromesh peers       Display connected DHT peers and reliability scores
  zeromesh status      Show node status and chunk storage telemetry
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.table import Table

from zeromesh.api.app import create_app
from zeromesh.node import ZeroMeshNode

app = typer.Typer(
    name="zeromesh",
    help="ZeroMesh: Decentralized P2P Encrypted File System",
    add_completion=False,
)
console = Console()


@app.command()
def start(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="TCP listen host (use 0.0.0.0 for LAN/Hotspot)"),
    port: int = typer.Option(7400, "--port", "-p", help="TCP listen port for P2P"),
    api_host: str = typer.Option("0.0.0.0", "--api-host", help="HTTP listen host for Web API/Prometheus"),
    api_port: int = typer.Option(8000, "--api-port", help="HTTP port for REST API"),
    advertise_host: str | None = typer.Option(
        None,
        "--advertise-host",
        "-a",
        help="Public, LAN, or Tailscale/VPN IP or hostname to announce to peers",
    ),
    advertise_port: int | None = typer.Option(
        None,
        "--advertise-port",
        help="Port to announce to peers if different from listen port (e.g. port forwarding)",
    ),
    data_dir: Path = typer.Option(Path("./data"), "--data-dir", "-d", help="Storage directory"),
    bootstrap: list[str] = typer.Option(
        [], "--bootstrap", "-b", help="Bootstrap peer addresses (host:port)"
    ),
) -> None:
    """Start a ZeroMesh node and its REST API."""
    import uvicorn

    console.print(f"[bold cyan]ZeroMesh Node[/bold cyan] starting on [green]{host}:{port}[/green]...")
    if advertise_host:
        console.print(f"Advertising address: [cyan]{advertise_host}:{advertise_port or port}[/cyan]")
    console.print(f"Data directory: [yellow]{data_dir.resolve()}[/yellow]")

    async def _run() -> None:
        node = ZeroMeshNode(
            host=host,
            port=port,
            advertise_host=advertise_host,
            advertise_port=advertise_port,
            data_dir=data_dir,
        )
        await node.start()

        if bootstrap:
            seeds = []
            for item in bootstrap:
                parts = item.split(":")
                seeds.append((parts[0], int(parts[1])))
            await node.bootstrap(seeds)

        api_app = create_app(node)
        config = uvicorn.Config(app=api_app, host=api_host, port=api_port, log_level="info")
        server = uvicorn.Server(config)

        try:
            display_host = "127.0.0.1" if api_host in ("0.0.0.0", "") else api_host
            console.print(f"[bold green]✓[/bold green] Web Dashboard: [cyan]http://{display_host}:{api_port}[/cyan]")
            console.print(f"[bold green]✓[/bold green] REST API Docs: [cyan]http://{display_host}:{api_port}/docs[/cyan]")
            console.print(f"[bold green]✓[/bold green] Prometheus:    [cyan]http://{display_host}:{api_port}/metrics[/cyan]")
            if api_host == "0.0.0.0":
                console.print(f"[dim]  (Also accessible to network peers on http://<your-ip>:{api_port}/)[/dim]")
            await server.serve()
        finally:
            await node.stop()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutdown requested by user.[/yellow]")


@app.command()
def upload(
    file_path: Path = typer.Argument(..., help="Path of local file to upload"),
    node_url: str = typer.Option("http://127.0.0.1:8000", "--node-url", help="API URL of local node"),
) -> None:
    """Upload a file to the network via local node's API."""
    if not file_path.exists():
        console.print(f"[bold red]Error:[/bold red] File {file_path} not found.")
        raise typer.Exit(1)

    console.print(f"Uploading [cyan]{file_path.name}[/cyan] ({file_path.stat().st_size} bytes)...")
    with httpx.Client(base_url=node_url, timeout=60.0) as client:
        with open(file_path, "rb") as f:
            resp = client.post("/api/files/upload", files={"file": (file_path.name, f)})

    if resp.status_code == 200:
        data = resp.json()
        console.print("[bold green]✓ Upload successful![/bold green]")
        console.print(f"Manifest ID: [bold yellow]{data['manifest_id']}[/bold yellow]")
        console.print(f"Chunks:      {data['num_chunks']}")
        console.print(f"Total size:  {data['total_size']} bytes")
    else:
        console.print(f"[bold red]Upload failed:[/bold red] {resp.text}")
        raise typer.Exit(1)


@app.command()
def download(
    manifest_id: str = typer.Argument(..., help="SHA-256 Manifest ID"),
    output_path: Path = typer.Argument(..., help="Destination file path"),
    node_url: str = typer.Option("http://127.0.0.1:8000", "--node-url", help="API URL of local node"),
) -> None:
    """Download and decrypt a file from the network."""
    console.print(f"Downloading manifest [yellow]{manifest_id[:16]}...[/yellow]")
    with httpx.Client(base_url=node_url, timeout=60.0) as client:
        resp = client.get(f"/api/files/{manifest_id}")

    if resp.status_code == 200:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(resp.content)
        console.print(f"[bold green]✓ Downloaded successfully to {output_path}[/bold green] ({len(resp.content)} bytes)")
    else:
        console.print(f"[bold red]Download failed:[/bold red] {resp.text}")
        raise typer.Exit(1)


@app.command(name="list-files")
def list_files(
    node_url: str = typer.Option("http://127.0.0.1:8000", "--node-url", help="API URL of local node"),
) -> None:
    """List all tracked files on the local node."""
    with httpx.Client(base_url=node_url, timeout=10.0) as client:
        resp = client.get("/api/files")

    if resp.status_code != 200:
        console.print(f"[bold red]Failed to fetch files:[/bold red] {resp.text}")
        raise typer.Exit(1)

    files = resp.json()
    if not files:
        console.print("[dim]No files stored yet.[/dim]")
        return

    table = Table(title="ZeroMesh Files")
    table.add_column("Manifest ID", style="yellow")
    table.add_column("Filename", style="cyan")
    table.add_column("Size (bytes)", justify="right")

    for f in files:
        table.add_row(f["manifest_id"][:16] + "...", f["filename"], str(f["total_size"]))
    console.print(table)


@app.command()
def peers(
    node_url: str = typer.Option("http://127.0.0.1:8000", "--node-url", help="API URL of local node"),
) -> None:
    """Display DHT routing table peers and reliability scores."""
    with httpx.Client(base_url=node_url, timeout=10.0) as client:
        resp = client.get("/api/peers")

    if resp.status_code != 200:
        console.print(f"[bold red]Failed to fetch peers:[/bold red] {resp.text}")
        raise typer.Exit(1)

    peer_list = resp.json()
    if not peer_list:
        console.print("[dim]No peers discovered yet.[/dim]")
        return

    table = Table(title="Connected DHT Peers")
    table.add_column("Node ID", style="magenta")
    table.add_column("Host:Port", style="green")
    table.add_column("Reliability Score", justify="right")

    for p in peer_list:
        score_style = "green" if p["score"] >= 0.7 else ("yellow" if p["score"] >= 0.4 else "red")
        table.add_row(
            p["node_id"][:16] + "...",
            f"{p['host']}:{p['port']}",
            f"[{score_style}]{p['score']:.4f}[/{score_style}]",
        )
    console.print(table)


@app.command()
def status(
    node_url: str = typer.Option("http://127.0.0.1:8000", "--node-url", help="API URL of local node"),
) -> None:
    """Check node health and storage stats."""
    with httpx.Client(base_url=node_url, timeout=10.0) as client:
        resp = client.get("/api/health")

    if resp.status_code != 200:
        console.print(f"[bold red]Node not reachable:[/bold red] {resp.text}")
        raise typer.Exit(1)

    data = resp.json()
    console.print(f"[bold green]Node Status:[/bold green] {data['status']}")
    console.print(f"Node ID:       [magenta]{data['node_id']}[/magenta]")
    console.print(f"Endpoint:      {data['host']}:{data['port']}")
    console.print(f"Known Peers:   [cyan]{data['total_peers']}[/cyan]")
    console.print(f"Stored Chunks: [yellow]{data['stored_chunks']}[/yellow]")
    console.print(f"Stored Bytes:  [yellow]{data['stored_bytes']}[/yellow]")


if __name__ == "__main__":
    app()
