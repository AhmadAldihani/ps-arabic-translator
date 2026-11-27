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
		assertEquals("مرحبا", m.items[0].lines[0].text)
		assertEquals(NRect(0.3f, 0.8f, 0.4f, 0.1f), m.items[0].rect)
		assertEquals(3000L, m.ttlMs)
	}

	@Test
	fun badInputIsIgnored()
	{
		assertNull(Protocol.parse("not json"))
		assertNull(Protocol.parse("""{"t":"nope"}"""))
		assertTrue(Protocol.parse("""{"t":"show","text":"  "}""") is Msg.Clear)
		assertNull((Protocol.parse("""{"t":"show","text":"x","rect":[0,0,0,0]}""") as Msg.Show).items[0].rect)
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

class LayoutAndItemsTest
{
	@Test
	fun parsesItemsWithSpeakers()
	{
		val m = Protocol.parse("""{"t":"show","items":[{"rect":[0.3,0.7,0.4,0.05],"lines":[{"s":"جيسون","t":"توقفي"},{"t":"خلاص"}]},{"lines":[{"t":"ثاني"}]}]}""") as Msg.Show
		assertEquals(2, m.items.size)
		assertEquals(CapLine("جيسون", "توقفي"), m.items[0].lines[0])
		assertEquals(CapLine(null, "خلاص"), m.items[0].lines[1])
		assertNull(m.items[1].rect)
	}

	@Test
	fun stackedBoxesNeverOverlap()
	{
		// Two subtitles whose Arabic boxes are taller than the gap between the English lines.
		val wants = listOf(
			StackLayout.Want(left = 600, width = 700, height = 120, bottom = 880),
			StackLayout.Want(left = 650, width = 600, height = 120, bottom = 950))
		val p = StackLayout.place(wants, 1080, 8)
		assertEquals(950, p[1].bottom)                 // the lower one stays on its original
		assertTrue(p[0].bottom <= p[1].top - 8)          // the upper one is pushed above it
		// A box on the other side of the screen is not moved.
		val q = StackLayout.place(listOf(StackLayout.Want(0, 300, 120, 900), StackLayout.Want(1500, 300, 120, 900)), 1080, 8)
		assertEquals(900, q[0].bottom); assertEquals(900, q[1].bottom)
	}
}

class StyleV2Test
{
	@Test
	fun newStyleFieldsAndLineHeight()
	{
		val s = CaptionStyle().merge(JSONObject("""{"font":"tajawal","outline":true,"outlineWidth":6,"speakerOwnLine":true,"placement":"top","font2":"x","widthMode":"bogus"}"""))
		assertEquals("tajawal", s.font)
		assertTrue(s.outline)
		assertEquals(6f, s.outlineWidth)
		assertTrue(s.speakerOwnLine)
		assertEquals("top", s.placement)
		assertEquals("match", s.widthMode)          // invalid value ignored
		val m = Protocol.parse("""{"t":"show","items":[{"rect":[0.3,0.8,0.4,0.05],"lh":0.04,"lines":[{"t":"x"}]}]}""") as Msg.Show
		assertEquals(0.04f, m.items[0].lineHeight)
		assertTrue(Protocol.parse("""{"t":"update"}""") is Msg.Update)
		assertEquals(34.56f, StackLayout.autoTextSize(43.2f, 1f), 0.01f)
	}
}

class PhoneItemsTest
{
	@Test
	fun parsesPhoneItems()
	{
		val m = Protocol.parse("""{"t":"show","items":[{"kind":"phone","bg":"#2a2a2a","fg":"#ffffff","rect":[0.7,0.5,0.2,0.03],"lh":0.03,"lines":[{"t":"وين أنت؟"}]}]}""") as Msg.Show
		val it = m.items[0]
		org.junit.Assert.assertEquals("phone", it.kind)
		org.junit.Assert.assertEquals(0xFF2A2A2A.toInt(), it.bg)
		org.junit.Assert.assertEquals(0xFFFFFFFF.toInt(), it.fg)
		org.junit.Assert.assertEquals("sub", (Protocol.parse("""{"t":"show","items":[{"lines":[{"t":"x"}]}]}""") as Msg.Show).items[0].kind)
	}
}
