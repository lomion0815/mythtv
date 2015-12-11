/*
 *  Class TestEITFixups
 *
 *  Copyright (C) Richard Hulme 2015
 *
 *   This program is free software; you can redistribute it and/or modify
 *   it under the terms of the GNU General Public License as published by
 *   the Free Software Foundation; either version 2 of the License, or
 *   (at your option) any later version.
 *
 *   This program is distributed in the hope that it will be useful,
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *   GNU General Public License for more details.
 *
 *   You should have received a copy of the GNU General Public License
 *   along with this program; if not, write to the Free Software
 *   Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301 USA
 */

#include <stdio.h>
#include "test_eitfixups.h"
#include "eitfixup.h"
#include "programdata.h"
#include "programinfo.h"

void printEvent( const DBEventEIT& event, const QString& name );
QString getSubtitleType(unsigned char type);
QString getAudioProps(unsigned char props);
QString getVideoProps(unsigned char props);


// Make this non-zero to enable dumping event details to stdout
#define DUMP_EVENTS 0

#if DUMP_EVENTS
    #define PRINT_EVENT(a) printEvent(a, #a)
#else
    #define PRINT_EVENT(a)
#endif
#define TEST_AND_ADD(t,m,s) do{if (t & m) {s += " | "#m;t &= ~m;}}while(0)

QString getSubtitleType(unsigned char type)
{
    QString ret;

    if (type == SUB_UNKNOWN)
    {
        ret = "SUB_UNKNOWN";
    }
    else
    {
        TEST_AND_ADD(type, SUB_HARDHEAR, ret);
        TEST_AND_ADD(type, SUB_NORMAL, ret);
        TEST_AND_ADD(type, SUB_ONSCREEN, ret);
        TEST_AND_ADD(type, SUB_SIGNED, ret);

        if (type != 0)
        {
            // Any other bits are shown numerically
            ret += QString(" | %1").arg(type);
        }

        // Remove initial ' | '
        ret = ret.remove(0,3);
    }

    return ret;
}

QString getAudioProps(unsigned char props)
{
    QString ret;

    if (props == AUD_UNKNOWN)
    {
        ret = "AUD_UNKNOWN";
    }
    else
    {
        TEST_AND_ADD(props, AUD_STEREO,       ret);
        TEST_AND_ADD(props, AUD_MONO,         ret);
        TEST_AND_ADD(props, AUD_SURROUND,     ret);
        TEST_AND_ADD(props, AUD_DOLBY,        ret);
        TEST_AND_ADD(props, AUD_HARDHEAR,     ret);
        TEST_AND_ADD(props, AUD_VISUALIMPAIR, ret);

        if (props != 0)
        {
            // Any other bits are shown numerically
            ret += QString(" | %1").arg(props);
        }

        // Remove initial ' | '
        ret = ret.remove(0,3);
    }

    return ret;
}

QString getVideoProps(unsigned char props)
{
    QString ret;

    if (props == VID_UNKNOWN)
    {
        ret = "VID_UNKNOWN";
    }
    else
    {
        TEST_AND_ADD(props, VID_HDTV,       ret);
        TEST_AND_ADD(props, VID_WIDESCREEN, ret);
        TEST_AND_ADD(props, VID_AVC,        ret);
        TEST_AND_ADD(props, VID_720,        ret);
        TEST_AND_ADD(props, VID_1080,       ret);
        TEST_AND_ADD(props, VID_DAMAGED,    ret);
        TEST_AND_ADD(props, VID_3DTV,       ret);

        if (props != 0)
        {
            // Any other bits are shown numerically
            ret += QString(" | %1").arg(props);
        }

        // Remove initial ' | '
        ret = ret.remove(0,3);
    }

    return ret;
}

void printEvent(const DBEventEIT& event, const QString& name)
{
    printf("\n------------Event - %s------------\n", name.toLocal8Bit().constData());
    printf("Title          %s\n",  event.title.toLocal8Bit().constData());
    printf("Subtitle       %s\n",  event.subtitle.toLocal8Bit().constData());
    printf("Description    %s\n",  event.description.toLocal8Bit().constData());
    printf("Part number    %3u\n", event.partnumber);
    printf("Part total     %3u\n", event.parttotal);
    printf("SubtitleType   %s\n",  getSubtitleType(event.subtitleType).toLocal8Bit().constData());
    printf("Audio props    %s\n",  getAudioProps(event.audioProps).toLocal8Bit().constData());
    printf("Video props    %s\n",  getVideoProps(event.videoProps).toLocal8Bit().constData());
    printf("\n");
}

DBEventEIT *TestEITFixups::SimpleDBEventEIT (uint fixup, QString title, QString subtitle, QString description)
{
    DBEventEIT *event = new DBEventEIT (1, // channel id
                                       title, // title
                                       subtitle, // subtitle
                                       description, // description
                                       "", // category
                                       ProgramInfo::kCategoryNone, // category_type
                                       QDateTime::fromString("2015-02-28T19:40:00Z", Qt::ISODate),
                                       QDateTime::fromString("2015-02-28T20:00:00Z", Qt::ISODate),
                                       EITFixUp::kFixGenericDVB | fixup,
                                       SUB_UNKNOWN,
                                       AUD_STEREO,
                                       VID_UNKNOWN,
                                       0.0f, // star rating
                                       "", // series id
                                       ""); // program id
    return event;
}

void TestEITFixups::testDEPro7Sat1()
{
    EITFixUp fixup;

    DBEventEIT *event = SimpleDBEventEIT (EITFixUp::kFixP7S1,
                                         "Titel",
                                         "Folgentitel, Mystery, USA 2011",
                                         "Beschreibung");

    PRINT_EVENT(*event);
    fixup.Fix(*event);
    PRINT_EVENT(*event);
    QCOMPARE(event->title,    QString("Titel"));
    QCOMPARE(event->subtitle, QString("Folgentitel"));
    QCOMPARE(event->airdate,  (unsigned short) 2011);

    DBEventEIT *event2 = SimpleDBEventEIT (EITFixUp::kFixP7S1,
                                           "Titel",
                                           "Kurznachrichten, D 2015",
                                           "Beschreibung");
    PRINT_EVENT(*event2);
    fixup.Fix(*event2);
    PRINT_EVENT(*event2);
    QCOMPARE(event2->subtitle, QString(""));
    QCOMPARE(event2->airdate,  (unsigned short) 2015);

    DBEventEIT *event3 = SimpleDBEventEIT (EITFixUp::kFixP7S1,
                                           "Titel",
                                           "Folgentitel",
                                           "Beschreibung");
    PRINT_EVENT(*event3);
    fixup.Fix(*event3);
    PRINT_EVENT(*event3);
    QCOMPARE(event3->subtitle, QString("Folgentitel"));
    QCOMPARE(event3->airdate,  (unsigned short) 0);

    DBEventEIT *event4 = SimpleDBEventEIT (EITFixUp::kFixP7S1,
                                           "Titel",
                                           "\"Lokal\", Ort, Doku-Soap, D 2015",
                                           "Beschreibung");
    PRINT_EVENT(*event4);
    fixup.Fix(*event4);
    PRINT_EVENT(*event4);
    QCOMPARE(event4->subtitle, QString("\"Lokal\", Ort"));
    QCOMPARE(event4->airdate,  (unsigned short) 2015);

    DBEventEIT *event5 = SimpleDBEventEIT (EITFixUp::kFixP7S1,
                                           "Titel",
                                           "In Morpheus' Armen, Science-Fiction, CDN/USA 2006",
                                           "Beschreibung");
    PRINT_EVENT(*event5);
    fixup.Fix(*event5);
    PRINT_EVENT(*event5);
    QCOMPARE(event5->subtitle, QString("In Morpheus' Armen"));
    QCOMPARE(event5->airdate,  (unsigned short) 2006);

    DBEventEIT *event6 = SimpleDBEventEIT (EITFixUp::kFixP7S1,
                                           "Titel",
                                           "Drei Kleintiere durchschneiden (1), Zeichentrick, J 2014",
                                           "Beschreibung");
    PRINT_EVENT(*event6);
    fixup.Fix(*event6);
    PRINT_EVENT(*event6);
    QCOMPARE(event6->subtitle, QString("Drei Kleintiere durchschneiden (1)"));
    QCOMPARE(event6->airdate,  (unsigned short) 2014);


}

void TestEITFixups::testSkyEpisodes()
{
    EITFixUp fixup;

    DBEventEIT *event = SimpleDBEventEIT (EITFixUp::kFixPremiere,
                                         "Titel",
                                         "Subtitle",
                                         "1. Staffel, Folge 7: Während Barbies Junggesellinnenabschieds in Miami streiten sich Nicole und Barbie wegen eines Abstechers in eine Stripbar.\u000aUSA 2015. 50 Min.");

    PRINT_EVENT(*event);
    fixup.Fix(*event);
    PRINT_EVENT(*event);
    QCOMPARE(event->description, QString("Während Barbies Junggesellinnenabschieds in Miami streiten sich Nicole und Barbie wegen eines Abstechers in eine Stripbar."));
    QCOMPARE(event->syndicatedepisodenumber,  QString("S1E7"));
    QCOMPARE(event->airdate,  (unsigned short) 2015);
	QVERIFY(!event->HasCredits());

    DBEventEIT *event2 = SimpleDBEventEIT (EITFixUp::kFixPremiere,
                                         "Titel",
                                         "Subtitle",
                                         "Bei einem Bombenanschlag in London kommen  - blabla - atemlosen Agententhriller mit starker Starpower.\u000a\u000a\u000a\u000a 93 Min.\u000aUSA 2015. Von James McTeigue, mit Milla Jovovich, Pierce Brosnan, Dylan McDermott.\u000aAb 16 Jahren");

    PRINT_EVENT(*event2);
    fixup.Fix(*event2);
    PRINT_EVENT(*event2);
    QCOMPARE(event2->description, QString("Bei einem Bombenanschlag in London kommen  - blabla - atemlosen Agententhriller mit starker Starpower.\u000a\u000a\u000a\u000a Ab 16 Jahren"));
    QCOMPARE(event2->syndicatedepisodenumber,  QString(""));
    QCOMPARE(event2->airdate,  (unsigned short) 2015);
	QVERIFY(event2->HasCredits());

    DBEventEIT *event3 = SimpleDBEventEIT (EITFixUp::kFixPremiere,
                                         "Titel",
                                         "Subtitle",
                                         "3. Staffel, Folge 21: Claire Guinness liebt Max ...blabla... ob nicht alles geändert werden sollte.\u000a2013. 20 Min.");

    PRINT_EVENT(*event3);
    fixup.Fix(*event3);
    PRINT_EVENT(*event3);
    QCOMPARE(event3->description, QString("Claire Guinness liebt Max ...blabla... ob nicht alles geändert werden sollte."));
    QCOMPARE(event3->syndicatedepisodenumber,  QString("S3E21"));
    QCOMPARE(event3->airdate,  (unsigned short) 2013);
    QVERIFY(!event3->HasCredits());
    
    DBEventEIT *event4 = SimpleDBEventEIT (EITFixUp::kFixPremiere,
                                         "Titel",
                                         "Subtitle",
                                         "2. Staffel, Folge 8: Wieder einmal rückt Weihnachten näher. Frys größter Wunsch ... blabla ... programmierter und gefährlicher Weihnachtsmann herum.\u000aUSA 1999. 25 Min. Von Peter Avanzino.");

    PRINT_EVENT(*event4);
    fixup.Fix(*event4);
    PRINT_EVENT(*event4);
    QCOMPARE(event4->description, QString("Wieder einmal rückt Weihnachten näher. Frys größter Wunsch ... blabla ... programmierter und gefährlicher Weihnachtsmann herum."));
    QCOMPARE(event4->syndicatedepisodenumber,  QString("S2E8"));
    QCOMPARE(event4->airdate,  (unsigned short) 1999);
	QVERIFY(event4->HasCredits());

}

QTEST_APPLESS_MAIN(TestEITFixups)

