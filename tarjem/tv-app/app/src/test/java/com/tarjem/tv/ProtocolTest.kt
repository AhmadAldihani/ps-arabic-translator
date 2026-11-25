package com.tarjem.tv

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ProtocolTest
{
	@Test
	fun parsesShowWithRect()
	{
		val m = Protocol.parse("""{"t":"show","text":"مرحبا","rect":[0.3,0.8,0.4,0.1],"ttl":3000}""")
		assertTrue(m is Msg.Show)
		m as Msg.Show
		assertEquals("مرحبا", m.text)
		assertEquals(NRect(0.3f, 0.8f, 0.4f, 0.1f), m.rect)
		assertEquals(3000L, m.ttlMs)
	}

	@Test
	fun badInputIsIgnored()
	{
		assertNull(Protocol.parse("not json"))
		assertNull(Protocol.parse("""{"t":"nope"}"""))
		assertTrue(Protocol.parse("""{"t":"show","text":"  "}""") is Msg.Clear)
		assertNull((Protocol.parse("""{"t":"show","text":"x","rect":[0,0,0,0]}""") as Msg.Show).rect)
	}

	@Test
	fun stylePatchMerges()
	{
		val s = CaptionStyle().merge(JSONObject("""{"size":40,"fg":"#FFFF00","bgAlpha":0.5,"placement":"bottom"}"""))
		assertEquals(40f, s.size)
		assertEquals(0xFFFFFF00.toInt(), s.fg)
		assertEquals(0.5f, s.bgAlpha)
		assertEquals("bottom", s.placement)
		assertEquals(CaptionStyle().bg, s.bg)
	}

	@Test
	fun colors()
	{
		assertEquals(0xFF102030.toInt(), Protocol.parseColor("#102030"))
		assertEquals(0x80102030.toInt(), Protocol.parseColor("#80102030"))
		assertNull(Protocol.parseColor("red"))
	}
}
