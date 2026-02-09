# lalo_spotify_tool.py
# Updated: Added clear instruction to double-check Client ID & Secret

import spotipy
from spotipy.oauth2 import SpotifyOAuth
import time
import os
import re
import shutil
import random
from pathlib import Path
from datetime import timedelta

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table
from rich.prompt import Prompt, Confirm

try:
    from dotenv import load_dotenv, set_key
except ImportError:
    os.system("pip install python-dotenv")
    from dotenv import load_dotenv, set_key

console = Console()

# ───────────────────────────────────────────────
# CONFIG - PROTECTION & SETTINGS
# ───────────────────────────────────────────────

REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPE = "user-library-modify user-library-read playlist-modify-public playlist-modify-private"
CACHE_PATH = ".cache-spotify"
ENV_FILE = ".env"

SAFE_THRESHOLD = 1000
SLOW_THRESHOLD_DELAY = 1.2
MIN_DELAY_BASE = 0.35
BACKOFF_FACTOR = 2.0
MAX_RETRIES = 5
WARNING_VERY_LARGE = 3000

SPEED_MODES = {
    "fast": 0.35,
    "balanced": 0.6,
    "accurate": 1.5
}

# ───────────────────────────────────────────────
# Credentials & Client
# ───────────────────────────────────────────────

def get_credentials():
    load_dotenv(ENV_FILE)
    return os.getenv("SPOTIPY_CLIENT_ID"), os.getenv("SPOTIPY_CLIENT_SECRET")


def change_credentials():
    console.print(Panel(
        "[bold cyan]Update Spotify API credentials[/bold cyan]\n\n"
        "Make sure you are copying the correct Client ID and Client Secret from your Spotify Developer Dashboard.\n"
        "Double-check that you didn't mix them up or include extra spaces.",
        title="Change Credentials", border_style="bright_blue"
    ))

    current_id, current_secret = get_credentials()

    new_id = Prompt.ask("[bold]Client ID[/bold]", default=current_id or "")
    new_secret = Prompt.ask("[bold]Client Secret[/bold]")

    if new_id:
        set_key(ENV_FILE, "SPOTIPY_CLIENT_ID", new_id.strip())
    if new_secret:
        set_key(ENV_FILE, "SPOTIPY_CLIENT_SECRET", new_secret.strip())

    console.print("[green]Credentials updated![/green]")

    clear_cache()


def clear_cache():
    console.print("\n[bold yellow]Delete cache & credentials?[/bold yellow]")
    console.print("This will:")
    console.print("  - Remove Spotify login cache (.cache-spotify)")
    console.print("  - Delete .env file (Client ID & Secret)")
    console.print("  - Force re-authentication next time")

    if not Confirm.ask("[bold red]Are you sure? This cannot be undone[/bold red]"):
        console.print("[yellow]Cancelled.[/yellow]")
        return False

    deleted = False

    if os.path.exists(CACHE_PATH):
        if os.path.isdir(CACHE_PATH):
            shutil.rmtree(CACHE_PATH)
        else:
            os.remove(CACHE_PATH)
        console.print("[green]Cache cleared[/green]")
        deleted = True

    if os.path.exists(ENV_FILE):
        os.remove(ENV_FILE)
        console.print("[green].env file deleted[/green]")
        deleted = True

    if deleted:
        console.print("\n[bold green]Cache & credentials successfully removed![/bold green]")
        console.print("[yellow]You will be asked to enter Client ID & Secret again on next operation.[/yellow]")
    else:
        console.print("[yellow]Nothing to delete.[/yellow]")

    return deleted


def get_spotify_client():
    client_id, client_secret = get_credentials()

    if not client_id or not client_secret:
        console.print(Panel(
            "[bold red]Credentials missing or reset[/bold red]\n\n"
            "Make sure you are copying the correct Client ID and Client Secret from your Spotify Developer Dashboard.\n"
            "Double-check that you didn't mix them up or include extra spaces.\n\n"
            "Go to: [link=https://developer.spotify.com/dashboard]Spotify Dashboard[/link]",
            title="Authentication Required", border_style="red"
        ))

        client_id = Prompt.ask("[bold]Client ID[/bold]")
        client_secret = Prompt.ask("[bold]Client Secret[/bold]")

        if not client_id or not client_secret:
            console.print("[red]Both values are required. Operation cancelled.[/red]")
            return None

        env_path = Path(ENV_FILE)
        env_path.touch(exist_ok=True)
        set_key(str(env_path), "SPOTIPY_CLIENT_ID", client_id.strip())
        set_key(str(env_path), "SPOTIPY_CLIENT_SECRET", client_secret.strip())

        console.print("[green]New credentials saved! You can now continue.[/green]")

    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        cache_path=CACHE_PATH,
        open_browser=True
    ))


# ───────────────────────────────────────────────
# Rate-limited wrapper
# ───────────────────────────────────────────────

def rate_limited_request(func, *args, **kwargs):
    retries = 0
    while retries < MAX_RETRIES:
        try:
            result = func(*args, **kwargs)
            time.sleep(MIN_DELAY_BASE + random.uniform(0, 0.15))
            return result
        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == 429:
                retry_after = int(e.headers.get('Retry-After', 5)) if e.headers else 5
                console.print(f"[yellow]Rate limit hit - waiting {retry_after}s...[/yellow]")
                time.sleep(retry_after + random.uniform(0, 2))
                retries += 1
                continue
            else:
                console.print(f"[red]API error: {e}[/red]")
                time.sleep(2 + retries * 2)
                retries += 1
    console.print("[red]Max retries reached - aborting[/red]")
    return None


# ───────────────────────────────────────────────
# Extract playlist ID
# ───────────────────────────────────────────────

def extract_playlist_id(link: str) -> str | None:
    match = re.search(r'playlist/([a-zA-Z0-9]+)', link)
    return match.group(1) if match else None


# ───────────────────────────────────────────────
# Fetch playlist info + tracks with metadata
# ───────────────────────────────────────────────

def get_playlist_info_and_tracks(sp, playlist_id: str) -> tuple[dict, list[dict]]:
    tracks = []
    playlist_info = {}

    try:
        # Get playlist metadata
        playlist_data = rate_limited_request(sp.playlist, playlist_id)
        if playlist_data:
            playlist_info = {
                "name": playlist_data.get("name", "Unknown Playlist"),
                "owner": playlist_data.get("owner", {}).get("display_name", "Unknown"),
                "total_tracks": playlist_data.get("tracks", {}).get("total", 0)
            }

        # Get tracks
        results = rate_limited_request(sp.playlist_items, playlist_id, additional_types=["track"])
        while results:
            for item in results["items"]:
                if track := item.get("track"):
                    if uri := track.get("uri"):
                        name = track.get("name", "Unknown")
                        artist = ", ".join(a["name"] for a in track.get("artists", [])) or "Unknown"
                        tracks.append({"uri": uri, "name": name, "artist": artist})
            if results.get("next"):
                results = rate_limited_request(sp.next, results)
            else:
                break

        return playlist_info, tracks

    except Exception as e:
        console.print(f"[red]Failed to load playlist: {e}[/red]")
        return {}, []


# ───────────────────────────────────────────────
# Show playlist preview (shows first 10 songs)
# ───────────────────────────────────────────────

def show_playlist_preview(playlist_info: dict, tracks: list[dict]):
    name = playlist_info.get("name", "Unknown Playlist")
    owner = playlist_info.get("owner", "Unknown")
    total = len(tracks)

    console.print(Panel(
        f"[bold cyan]Playlist Preview[/bold cyan]\n"
        f"Name: [white]{name}[/white]\n"
        f"Owner: [white]{owner}[/white]\n"
        f"Total tracks: [green]{total}[/green]\n\n"
        f"[dim]First 10 songs:[/dim]",
        border_style="bright_blue"
    ))

    if tracks:
        preview_table = Table(show_header=False, show_lines=True, border_style="dim")
        preview_table.add_column("Song", style="white")
        preview_table.add_column("Artist", style="dim")

        for track in tracks[:10]:
            preview_table.add_row(track["name"], track["artist"])

        console.print(preview_table)
    else:
        console.print("[dim]No tracks to preview[/dim]")


# ───────────────────────────────────────────────
# Process songs (add or remove) with adaptive protection
# ───────────────────────────────────────────────

def process_songs(sp, tracks: list[dict], mode: str = "add"):
    total = len(tracks)
    if total == 0:
        console.print("[yellow]No tracks to process.[/yellow]")
        return

    effective_delay = None
    if total > SAFE_THRESHOLD:
        console.print(Panel(
            f"[yellow bold]Large playlist detected ({total} songs)[/yellow bold]\n"
            f"→ Safety mode activated: delay increased to ≥ {SLOW_THRESHOLD_DELAY}s per song\n"
            "→ This protects against rate limiting or temporary restrictions",
            title="Safety Protection", border_style="yellow"
        ))
        effective_delay = SLOW_THRESHOLD_DELAY
    else:
        console.print("\n[bold]Choose speed mode:[/bold]")
        console.print("  [1] Fast (quick but higher risk)")
        console.print("  [2] Balanced (recommended)")
        console.print("  [3] Accurate (safest)")
        console.print("  [4] Back to dashboard")
        speed_choice = Prompt.ask("Select", choices=["1", "2", "3", "4"], default="2")

        if speed_choice == "4":
            console.print("[yellow]Returning to dashboard...[/yellow]")
            return

        effective_delay = SPEED_MODES[{"1": "fast", "2": "balanced", "3": "accurate"}[speed_choice]]

    action_text = "add" if mode == "add" else "remove"
    console.print(Panel(
        f"[bold cyan]Ready to {action_text} {total} songs[/bold cyan]\n"
        f"Mode: [yellow]{mode.capitalize()}[/yellow]\n"
        f"Delay: [yellow]{effective_delay:.2f}s[/yellow]\n"
        f"Estimated time: [green]{timedelta(seconds=int(total * (effective_delay + 0.5)))}[/green]",
        title="Summary", border_style="bright_magenta"
    ))

    confirm_msg = f"Are you sure you want to {action_text} this playlist to/from Liked Songs?"
    if not Confirm.ask(confirm_msg):
        console.print("[yellow]Cancelled.[/yellow]")
        return

    console.print(f"\n[bold green]{mode.capitalize()}ing songs...[/bold green]\n")

    start_time = time.time()
    skipped = 0
    processed = 0

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=None),
        "[progress.percentage]{task.percentage:>3.1f}%",
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console
    ) as progress:
        task = progress.add_task(f"[cyan]{mode.capitalize()}ing...", total=total)

        for i, track in enumerate(tracks[::-1], 1):
            uri = track["uri"]
            display = f"{track['name']} – {track['artist']}"

            try:
                if mode == "add":
                    is_liked = rate_limited_request(sp.current_user_saved_tracks_contains, tracks=[uri])[0]
                    if is_liked:
                        console.print(f"[yellow]Skipped (already liked):[/yellow] {display}")
                        skipped += 1
                    else:
                        rate_limited_request(sp.current_user_saved_tracks_add, tracks=[uri])
                        console.print(f"[green]Added:[/green] {display}")
                        processed += 1
                elif mode == "remove":
                    is_liked = rate_limited_request(sp.current_user_saved_tracks_contains, tracks=[uri])[0]
                    if is_liked:
                        rate_limited_request(sp.current_user_saved_tracks_delete, tracks=[uri])
                        console.print(f"[red]Removed:[/red] {display}")
                        processed += 1
                    else:
                        console.print(f"[yellow]Skipped (not liked):[/yellow] {display}")
                        skipped += 1

                elapsed = time.time() - start_time
                if i > 5:
                    eta_seconds = (elapsed / i) * (total - i)
                    progress.update(task, description=f"[cyan]{mode.capitalize()}ing... (ETA: {timedelta(seconds=int(eta_seconds))})[/cyan]")

                progress.update(task, advance=1)

            except Exception as e:
                console.print(f"[red]Error on {display}:[/red] {e}")
                time.sleep(3 + random.uniform(0, 2))

            time.sleep(effective_delay + random.uniform(0, 0.15))

    console.print("\n[bold green]Completed![/bold green]")
    console.print(f"Processed: [green]{processed}[/green] songs")
    console.print(f"Skipped: [yellow]{skipped}[/yellow] songs")


# ───────────────────────────────────────────────
# Create playlist from Liked Songs
# ───────────────────────────────────────────────

def create_playlist_from_liked(sp):
    console.print("\n[bold cyan]Create Playlist from Liked Songs[/bold cyan]")

    name = Prompt.ask("New playlist name", default="My Liked Songs Backup")
    limit_str = Prompt.ask("How many recent liked songs? (number or 'all')", default="100")

    try:
        limit = int(limit_str) if limit_str.lower() != "all" else None
    except ValueError:
        limit = None

    console.print("[yellow]Fetching your Liked Songs...[/yellow]")

    try:
        liked = []
        results = rate_limited_request(sp.current_user_saved_tracks, limit=limit or 50)
        while results:
            for item in results["items"]:
                if track := item.get("track"):
                    if uri := track.get("uri"):
                        liked.append(uri)
            if results.get("next") and (limit is None or len(liked) < limit):
                results = rate_limited_request(sp.next, results)
            else:
                break

        if limit and len(liked) > limit:
            liked = liked[:limit]

        console.print(f"[green]Found {len(liked)} liked songs[/green]")

        if not Confirm.ask(f"Create playlist '{name}' with {len(liked)} songs?"):
            console.print("[yellow]Cancelled.[/yellow]")
            return

        user_id = sp.current_user()["id"]
        playlist = rate_limited_request(
            sp.user_playlist_create,
            user=user_id,
            name=name,
            public=False,
            description="Created by Lalo Spotify Tool"
        )

        console.print("\n[bold green]Adding tracks to new playlist...[/bold green]\n")

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            console=console
        ) as progress:
            task = progress.add_task("[cyan]Adding...", total=len(liked))

            for i in range(0, len(liked), 100):
                batch = liked[i:i+100]
                rate_limited_request(sp.playlist_add_items, playlist["id"], batch)
                progress.update(task, advance=len(batch))

        console.print(f"[bold green]Success![/bold green] New playlist: [cyan]{name}[/cyan]")
        console.print(f"Link: [link={playlist['external_urls']['spotify']}]{playlist['external_urls']['spotify']}[/link]")

    except Exception as e:
        console.print(f"[red]Error creating playlist: {e}[/red]")


# ───────────────────────────────────────────────
# Dashboard
# ───────────────────────────────────────────────

def show_dashboard():
    console.print("\n" * 2)
    console.print(Panel(
        "[bold magenta]LALO SPOTIFY TOOL[/bold magenta]",
        style="bold magenta on black",
        border_style="bold magenta",
        padding=(2, 6),
        expand=True,
        title_align="center",
    ), justify="center")
    
    console.print(Panel(
        "[bold cyan]Credit to DamnLalo[/bold cyan]",
        style="cyan",
        border_style="dim",
        padding=(0, 4),
        expand=False,
    ), justify="center")

    console.print("\n[bold]Dashboard[/bold]\n")

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("Action", style="cyan")

    table.add_row("1", "Add playlist to Liked Songs")
    table.add_row("2", "Remove playlist from Liked Songs")
    table.add_row("3", "Create playlist from Liked Songs")
    table.add_row("4", "Change Client ID & Secret")
    table.add_row("5", "Delete cache & .env file")
    table.add_row("6", "Quit")

    console.print(table)


def main():
    show_dashboard()

    while True:
        choice = Prompt.ask("\nSelect an option", choices=["1", "2", "3", "4", "5", "6"], default="1")

        if choice == "6":
            console.print("[blue]Goodbye! :wave:[/blue]")
            break

        elif choice == "5":
            clear_cache()
            show_dashboard()
            continue

        elif choice == "4":
            change_credentials()
            show_dashboard()
            continue

        sp = get_spotify_client()
        if not sp:
            console.print("[red]Cannot proceed without valid credentials.[/red]")
            show_dashboard()
            continue

        if choice == "3":
            create_playlist_from_liked(sp)
            show_dashboard()
            continue

        # Add or Remove
        console.print("\n[bold]Paste the Spotify playlist link[/bold] (or 'b' to go back):")
        link = Prompt.ask("> ").strip()

        if link.lower() in ('b', 'back'):
            show_dashboard()
            continue

        playlist_id = extract_playlist_id(link)
        if not playlist_id:
            console.print("[red]Invalid link[/red] – must contain '/playlist/'")
            continue

        console.print(f"[dim]Playlist ID:[/dim] [cyan]{playlist_id}[/cyan]")

        console.print("[yellow]Loading playlist info and tracks...[/yellow]")
        playlist_info, tracks = get_playlist_info_and_tracks(sp, playlist_id)

        if not tracks:
            console.print("[yellow]No tracks loaded.[/yellow]")
            show_dashboard()
            continue

        console.print(f"[green]Found {len(tracks)} tracks[/green]")

        # Show preview (first 10 songs)
        show_playlist_preview(playlist_info, tracks)

        mode = "add" if choice == "1" else "remove"
        process_songs(sp, tracks, mode=mode)

        console.print("\n[bold cyan]Returning to dashboard...[/bold cyan]")
        show_dashboard()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bright_black]Stopped by user[/bright_black]")