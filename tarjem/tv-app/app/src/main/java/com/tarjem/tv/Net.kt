// Tarjem TV — LAN server (TCP, JSON lines) and discovery responder (UDP broadcast).

package com.tarjem.tv

import android.util.Log
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.io.PrintWriter
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.Inet4Address
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.util.Collections

private const val TAG = "TarjemNet"

/** A connected laptop. [send] may be called from any thread. */
class Client(private val socket: Socket)
{
	@Volatile var name: String = socket.inetAddress.hostAddress ?: "?"
	private val out = PrintWriter(OutputStreamWriter(socket.getOutputStream(), Charsets.UTF_8), true)

	fun send(line: String)
	{
		synchronized(out) { out.println(line) }
	}

	fun close()
	{
		try { socket.close() } catch(_: Exception) { }
	}
}

class NetServer(
	private val onMessage: (Client, Msg) -> Unit,
	private val onClientsChanged: (List<Client>) -> Unit
)
{
	@Volatile var port: Int = SERVER_PORT
		private set
	@Volatile private var running = false
	private var server: ServerSocket? = null
	private var discovery: DatagramSocket? = null
	private val clients = Collections.synchronizedList(mutableListOf<Client>())
	var describe: () -> String = { "{}" }

	fun start()
	{
		if(running)
			return
		running = true
		Thread({ acceptLoop() }, "tarjem-tcp").apply { isDaemon = true }.start()
		Thread({ discoveryLoop() }, "tarjem-udp").apply { isDaemon = true }.start()
	}

	fun stop()
	{
		running = false
		try { server?.close() } catch(_: Exception) { }
		try { discovery?.close() } catch(_: Exception) { }
		synchronized(clients) { clients.forEach { it.close() }; clients.clear() }
		onClientsChanged(emptyList())
	}

	fun clientNames(): List<String> = synchronized(clients) { clients.map { it.name } }

	private fun acceptLoop()
	{
		val ss = bind() ?: return
		server = ss
		while(running)
		{
			val s = try { ss.accept() } catch(e: SocketException) { break } catch(e: Exception) { continue }
			s.tcpNoDelay = true
			val c = Client(s)
			clients.add(c)
			onClientsChanged(clients.toList())
			Thread({ readLoop(c, s) }, "tarjem-client").apply { isDaemon = true }.start()
		}
	}

	private fun bind(): ServerSocket?
	{
		for(p in SERVER_PORT..SERVER_PORT + 10)
		{
			if(p == DISCOVERY_PORT)
				continue
			try
			{
				val ss = ServerSocket()
				ss.reuseAddress = true
				ss.bind(InetSocketAddress(p))
				port = p
				return ss
			}
			catch(e: Exception)
			{
				Log.w(TAG, "port $p busy: $e")
			}
		}
		return null
	}

	private fun readLoop(c: Client, s: Socket)
	{
		try
		{
			val reader = BufferedReader(InputStreamReader(s.getInputStream(), Charsets.UTF_8))
			while(running)
			{
				val line = reader.readLine() ?: break
				val msg = Protocol.parse(line) ?: continue
				if(msg is Msg.Hello)
					c.name = msg.name
				onMessage(c, msg)
			}
		}
		catch(e: Exception)
		{
			Log.i(TAG, "client gone: $e")
		}
		finally
		{
			c.close()
			clients.remove(c)
			onClientsChanged(clients.toList())
		}
	}

	private fun discoveryLoop()
	{
		val sock = try
		{
			DatagramSocket(null).apply {
				reuseAddress = true
				broadcast = true
				bind(InetSocketAddress(DISCOVERY_PORT))
			}
		}
		catch(e: Exception)
		{
			Log.w(TAG, "discovery unavailable: $e")
			return
		}
		discovery = sock
		val buf = ByteArray(512)
		while(running)
		{
			try
			{
				val p = DatagramPacket(buf, buf.size)
				sock.receive(p)
				val text = String(p.data, 0, p.length, Charsets.UTF_8).trim()
				if(!text.startsWith(DISCOVERY_REQUEST))
					continue
				val reply = describe().toByteArray(Charsets.UTF_8)
				sock.send(DatagramPacket(reply, reply.size, p.address, p.port))
			}
			catch(e: SocketException)
			{
				break
			}
			catch(e: Exception)
			{
				Log.w(TAG, "discovery: $e")
			}
		}
	}
}

object NetInfo
{
	/** IPv4 addresses of this TV on the local network (Wi-Fi or Ethernet). */
	fun localAddresses(): List<String> = try
	{
		NetworkInterface.getNetworkInterfaces().toList()
			.filter { it.isUp && !it.isLoopback }
			.flatMap { it.inetAddresses.toList() }
			.filterIsInstance<Inet4Address>()
			.mapNotNull { it.hostAddress }
	}
	catch(e: Exception)
	{
		emptyList()
	}
}
