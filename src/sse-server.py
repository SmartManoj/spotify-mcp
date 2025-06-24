from typing import Any, Optional
import httpx
import os
import json
import logging
import sys
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from mcp.server.sse import SseServerTransport
from starlette.requests import Request
from starlette.routing import Mount, Route
from mcp.server import Server
import uvicorn

from spotify_mcp import spotify_api
from spotify_mcp.utils import normalize_redirect_uri

# Initialize FastMCP server for Spotify tools (SSE)
mcp = FastMCP("spotify-mcp")

# Setup logger
def setup_logger():
    class Logger:
        def info(self, message):
            print(f"[INFO] {message}", file=sys.stderr)

        def error(self, message):
            print(f"[ERROR] {message}", file=sys.stderr)

    return Logger()

logger = setup_logger()

# Normalize the redirect URI to meet Spotify's requirements
if spotify_api.REDIRECT_URI:
    spotify_api.REDIRECT_URI = normalize_redirect_uri(spotify_api.REDIRECT_URI)
spotify_client = spotify_api.Client(logger)


@mcp.tool()
async def playback(action: str, spotify_uri: Optional[str] = None, num_skips: Optional[int] = 1) -> str:
    """Manages the current playback with the following actions:
    - get: Get information about user's current track.
    - start: Starts playing new item or resumes current playback if called with no uri.
    - pause: Pauses current playback.
    - skip: Skips current track.
    """
    try:
        match action:
            case "get":
                logger.info("Attempting to get current track")
                curr_track = spotify_client.get_current_track()
                if curr_track:
                    logger.info(f"Current track retrieved: {curr_track.get('name', 'Unknown')}")
                    return json.dumps(curr_track, indent=2)
                logger.info("No track currently playing")
                return "No track playing."
            case "start":
                logger.info(f"Starting playback with uri: {spotify_uri}")
                spotify_client.start_playback(spotify_uri=spotify_uri)
                logger.info("Playback started successfully")
                return "Playback starting."
            case "pause":
                logger.info("Attempting to pause playback")
                spotify_client.pause_playback()
                logger.info("Playback paused successfully")
                return "Playback paused."
            case "skip":
                logger.info(f"Skipping {num_skips} tracks.")
                spotify_client.skip_track(n=num_skips)
                return "Skipped to next track."
            case _:
                return f"Unknown action: {action}. Supported actions are: get, start, pause, skip."
    except Exception as e:
        logger.error(f"Playback error: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
async def search(query: str, qtype: str = "track", limit: int = 10) -> str:
    """Search for tracks, albums, artists, or playlists on Spotify."""
    try:
        logger.info(f"Performing search: {query}, type: {qtype}, limit: {limit}")
        search_results = spotify_client.search(
            query=query,
            qtype=qtype,
            limit=limit
        )
        logger.info("Search completed successfully.")
        return json.dumps(search_results, indent=2)
    except Exception as e:
        logger.error(f"Search error: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
async def queue(action: str, track_id: Optional[str] = None) -> str:
    """Manage the playback queue - get the queue or add tracks."""
    try:
        logger.info(f"Queue operation: {action}")
        match action:
            case "add":
                if not track_id:
                    logger.error("track_id is required for add to queue.")
                    return "track_id is required for add action"
                spotify_client.add_to_queue(track_id)
                return "Track added to queue."
            case "get":
                queue_data = spotify_client.get_queue()
                return json.dumps(queue_data, indent=2)
            case _:
                return f"Unknown queue action: {action}. Supported actions are: add, get."
    except Exception as e:
        logger.error(f"Queue error: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
async def get_info(item_uri: str) -> str:
    """Get detailed information about a Spotify item (track, album, artist, or playlist)."""
    try:
        logger.info(f"Getting item info for: {item_uri}")
        item_info = spotify_client.get_info(item_uri=item_uri)
        return json.dumps(item_info, indent=2)
    except Exception as e:
        logger.error(f"GetInfo error: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
async def playlist(action: str, playlist_id: Optional[str] = None, 
                  track_ids: Optional[str] = None, name: Optional[str] = None, 
                  description: Optional[str] = None) -> str:
    """Manage Spotify playlists.
    - get: Get a list of user's playlists.
    - get_tracks: Get tracks in a specific playlist.
    - add_tracks: Add tracks to a specific playlist.
    - remove_tracks: Remove tracks from a specific playlist.
    - change_details: Change details of a specific playlist.
    """
    try:
        logger.info(f"Playlist operation: {action}")
        match action:
            case "get":
                logger.info("Getting current user's playlists")
                playlists = spotify_client.get_current_user_playlists()
                return json.dumps(playlists, indent=2)
            case "get_tracks":
                if not playlist_id:
                    logger.error("playlist_id is required for get_tracks action.")
                    return "playlist_id is required for get_tracks action."
                logger.info(f"Getting tracks in playlist: {playlist_id}")
                tracks = spotify_client.get_playlist_tracks(playlist_id)
                return json.dumps(tracks, indent=2)
            case "add_tracks":
                if not playlist_id or not track_ids:
                    logger.error("playlist_id and track_ids are required for add_tracks action.")
                    return "playlist_id and track_ids are required for add_tracks action."
                try:
                    track_ids_list = json.loads(track_ids) if isinstance(track_ids, str) else track_ids
                except json.JSONDecodeError:
                    logger.error("track_ids must be a valid JSON array.")
                    return "Error: track_ids must be a valid JSON array."
                logger.info(f"Adding tracks to playlist: {playlist_id}")
                spotify_client.add_tracks_to_playlist(playlist_id=playlist_id, track_ids=track_ids_list)
                return "Tracks added to playlist."
            case "remove_tracks":
                if not playlist_id or not track_ids:
                    logger.error("playlist_id and track_ids are required for remove_tracks action.")
                    return "playlist_id and track_ids are required for remove_tracks action."
                try:
                    track_ids_list = json.loads(track_ids) if isinstance(track_ids, str) else track_ids
                except json.JSONDecodeError:
                    logger.error("track_ids must be a valid JSON array.")
                    return "Error: track_ids must be a valid JSON array."
                logger.info(f"Removing tracks from playlist: {playlist_id}")
                spotify_client.remove_tracks_from_playlist(playlist_id=playlist_id, track_ids=track_ids_list)
                return "Tracks removed from playlist."
            case "change_details":
                if not playlist_id:
                    logger.error("playlist_id is required for change_details action.")
                    return "playlist_id is required for change_details action."
                if not name and not description:
                    logger.error("At least one of name or description is required.")
                    return "At least one of name or description is required."
                logger.info(f"Changing playlist details: {playlist_id}")
                spotify_client.change_playlist_details(
                    playlist_id=playlist_id,
                    name=name,
                    description=description
                )
                return "Playlist details changed."
            case _:
                return f"Unknown playlist action: {action}. Supported actions are: get, get_tracks, add_tracks, remove_tracks, change_details."
    except Exception as e:
        logger.error(f"Playlist error: {str(e)}")
        return f"Error: {str(e)}"


def create_starlette_app(mcp_server: Server, *, debug: bool = False) -> Starlette:
    """Create a Starlette application that can serve the provided mcp server with SSE."""
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> None:
        async with sse.connect_sse(
                request.scope,
                request.receive,
                request._send,  # noqa: SLF001
        ) as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )

    return Starlette(
        debug=debug,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )


if __name__ == "__main__":
    mcp_server = mcp._mcp_server  # noqa: WPS437

    import argparse
    
    parser = argparse.ArgumentParser(description='Run Spotify MCP SSE-based server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8080, help='Port to listen on')
    args = parser.parse_args()

    # Bind SSE request handling to MCP server
    starlette_app = create_starlette_app(mcp_server, debug=True)

    uvicorn.run(starlette_app, host=args.host, port=args.port) 