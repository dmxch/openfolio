---
id: "api-erste-abfrage"
title: "Erste Abfrage gegen die externe API"
summary: "So rufst du mit einem API-Token zum ersten Mal Daten aus deinem Portfolio ab."
section: "api"
order: 20
---

Die externe API liefert deine Portfolio-Daten als JSON. Du brauchst dafür einen Token, wie ihn [API-Token erstellen und widerrufen](#api-schluessel-erstellen) beschreibt.

## Adresse und Header

Die Basis-Adresse hat die Form `https://<deine-instanz>/api/v1/external`. Im Tab **API-Tokens** zeigt OpenFolio sie unter «Base URL für diese Instanz» an. Dort kopierst du sie mit einem Klick.

Du sendest den Token im Header `X-API-Key`. Verwende immer HTTPS, weil der Header sonst im Klartext reist.

## Das erste Beispiel

Der Endpunkt `/portfolio/summary` liefert die Totale, die Allokationen und die Positionsliste. Der Aufruf lautet: `curl -H "X-API-Key: ofk_..." https://<deine-instanz>/api/v1/external/portfolio/summary`. Ersetze `ofk_...` durch deinen Token und `<deine-instanz>` durch die Adresse deiner Instanz.

Die Antwort enthält unter anderem `total_invested_chf`, `total_market_value_chf`, `total_pnl_chf` und die Liste `positions`. Die Werte stammen bis zu 60 Sekunden aus dem Zwischenspeicher.

## Fehlermeldungen

Bei einem fehlenden, ungültigen, abgelaufenen oder widerrufenen Token antwortet die API mit 401. Eine Änderung ohne Schreib-Recht ergibt 403. Eine Überschreitung der Limits ergibt 429.

## Limits

Die meisten Routen erlauben 30 Abfragen pro Minute. Alle Tokens eines Kontos teilen sich dieses Budget je Route. Lese-Routen mit Ticker oder ID im Pfad erlauben 120 pro Minute. Alle Aufrufe einer IP-Adresse zusammen begrenzt der Webserver auf 300 pro Minute. Speichere Antworten deshalb zwischen, statt sie oft neu abzurufen.

## Weitere Endpunkte

Die vollständige Liste mit Beispiel-Antworten steht in der Datei `docs/EXTERNAL_API.md` im öffentlichen OpenFolio-Repository.
