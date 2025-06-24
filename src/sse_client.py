import asyncio
import json
import os
import sys
from typing import Optional
from contextlib import AsyncExitStack

from mcp import ClientSession
from mcp.client.sse import sse_client

from litellm import completion
from dotenv import load_dotenv

load_dotenv()  # load environment variables from .env

class SpotifyMCPClient:
    def __init__(self):
        # Initialize session and client objects
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.model = "gemini/gemini-2.5-flash"

    async def connect_to_sse_server(self, server_url: str):
        """Connect to an MCP server running with SSE transport"""
        print(f"🔌 Connecting to SSE server at: {server_url}")
        
        # Store the context managers so they stay alive
        self._streams_context = sse_client(url=server_url)
        streams = await self._streams_context.__aenter__()

        self._session_context = ClientSession(*streams)
        self.session: ClientSession = await self._session_context.__aenter__()

        # Initialize
        await self.session.initialize()

        # List available tools to verify connection
        print("✅ Initialized SSE client...")
        print("📋 Listing available tools...")
        response = await self.session.list_tools()
        tools = response.tools
        print(f"🎧 Connected to Spotify MCP server with tools: {[tool.name for tool in tools]}")

    async def cleanup(self):
        """Properly clean up the session and streams"""
        if getattr(self, "_session_context", None):
            await self._session_context.__aexit__(None, None, None)
        if getattr(self, "_streams_context", None):
            await self._streams_context.__aexit__(None, None, None)

    async def test_tool(self, tool_name: str, arguments: dict) -> str:
        """Test a specific tool directly"""
        try:
            print(f"\n🔧 Testing {tool_name} with args: {arguments}")
            
            # Call the tool
            result = await self.session.call_tool(tool_name, arguments)
            
            # Extract text content from MCP response
            if hasattr(result, 'content') and result.content:
                if hasattr(result.content[0], 'text'):
                    response_text = result.content[0].text
                else:
                    response_text = str(result.content[0])
            else:
                response_text = str(result.content)
            
            print(f"✅ {tool_name} test completed")
            print(f"📄 Response: {response_text[:200]}..." if len(response_text) > 200 else f"📄 Response: {response_text}")
            return response_text
            
        except Exception as e:
            print(f"❌ {tool_name} test failed: {e}")
            return f"Error: {str(e)}"

    async def test_all_tools(self):
        """Test all available Spotify tools"""
        print("\n🚀 Starting Spotify MCP Tool Tests")
        print("=" * 50)
        
        try:
            # Test playback tools
            print("\n🎵 Testing Playback Tools")
            print("-" * 30)
            await self.test_tool("playback", {"action": "get"})
            await self.test_tool("playback", {"action": "pause"})
            await self.test_tool("playback", {"action": "start"})
            
            # Test search tool
            print("\n🔍 Testing Search Tool")
            print("-" * 30)
            await self.test_tool("search", {
                "query": "Bohemian Rhapsody",
                "qtype": "track",
                "limit": 5
            })
            
            # Test queue tools
            print("\n📋 Testing Queue Tools")
            print("-" * 30)
            await self.test_tool("queue", {"action": "get"})
            
            # Test get info tool
            print("\nℹ️ Testing Get Info Tool")
            print("-" * 30)
            await self.test_tool("get_info", {
                "item_uri": "spotify:track:3z8h0TU7ReDPLIbEnYhWZb"  # Bohemian Rhapsody
            })
            
            # Test playlist tools
            print("\n📚 Testing Playlist Tools")
            print("-" * 30)
            await self.test_tool("playlist", {"action": "get"})
            
            print("\n✅ All tests completed!")
            
        except Exception as e:
            print(f"❌ Test suite failed: {e}")

    async def process_query(self, query: str) -> str:
        """Process a query using Gemini and available tools"""
        messages = [
            {
                "role": "user",
                "content": query
            }
        ]

        response = await self.session.list_tools()
        available_tools = [{ 
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.inputSchema
            }
        } for tool in response.tools]

        try:
            # Initial Gemini API call
            response = completion(
                model=self.model,
                messages=messages,
                tools=available_tools,
                max_tokens=1000
            )

            # Process response and handle tool calls
            tool_results = []
            final_text = []

            for choice in response.choices:
                message = choice.message
                if message.content:
                    final_text.append(message.content)
                
                if hasattr(message, 'tool_calls') and message.tool_calls:
                    for tool_call in message.tool_calls:
                        tool_name = tool_call.function.name
                        tool_args = json.loads(tool_call.function.arguments)
                        
                        # Execute tool call
                        result = await self.session.call_tool(tool_name, tool_args)
                        tool_results.append({"call": tool_name, "result": result})
                        final_text.append(f"[Calling tool {tool_name} with args {tool_args}]")

                        # Extract text content from MCP response
                        tool_response_text = ""
                        if hasattr(result, 'content') and result.content:
                            if hasattr(result.content[0], 'text'):
                                tool_response_text = result.content[0].text
                            else:
                                tool_response_text = str(result.content[0])
                        else:
                            tool_response_text = str(result.content)

                        # Continue conversation with tool results (use plain text)
                        messages.append({
                            "role": "assistant",
                            "content": message.content or ""
                        })
                        messages.append({
                            "role": "user", 
                            "content": tool_response_text
                        })

                        # Get next response from Gemini
                        response = completion(
                            model=self.model,
                            messages=messages,
                            max_tokens=1000
                        )

                        if response.choices and response.choices[0].message.content:
                            final_text.append(response.choices[0].message.content)

            return "\n".join(final_text)
        except Exception as e:
            return f"Error processing query: {str(e)}"

    async def chat_loop(self):
        """Run an interactive chat loop"""
        print("\n🎧 Spotify MCP Client Started!")
        print("Type your queries or 'quit' to exit.")
        print("Type 'test' to run all tool tests.")
        
        while True:
            try:
                query = input("\nQuery: ").strip()
                
                if query.lower() == 'quit':
                    break
                elif query.lower() == 'test':
                    await self.test_all_tools()
                    continue
                    
                response = await self.process_query(query)
                print("\n" + response)
                    
            except Exception as e:
                print(f"\nError: {str(e)}")


async def main():
    if len(sys.argv) < 2:
        print("Usage: python client.py <URL of SSE MCP server (i.e. http://localhost:8080/sse)>")
        print("Example: python client.py http://localhost:8080/sse")
        sys.exit(1)

    client = SpotifyMCPClient()
    try:
        await client.connect_to_sse_server(server_url=sys.argv[1])
        
        # Ask user what they want to do
        print("\nWhat would you like to do?")
        print("1. Run all tool tests")
        print("2. Start interactive chat")
        print("3. Both")
        
        choice = input("Enter choice (1/2/3): ").strip()
        
        if choice == "1":
            await client.test_all_tools()
        elif choice == "2":
            await client.chat_loop()
        elif choice == "3":
            await client.test_all_tools()
            await client.chat_loop()
        else:
            print("Invalid choice. Running tests by default.")
            await client.test_all_tools()
            
    finally:
        await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main()) 