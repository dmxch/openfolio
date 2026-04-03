import { Link } from 'react-router-dom'

export default function Terms() {
  return (
    <div className="min-h-screen bg-body">
      <div className="max-w-3xl mx-auto px-4 py-12 space-y-6">
        <div>
          <h1 className="text-xl font-bold text-text-primary">Allgemeine Geschäftsbedingungen (AGB)</h1>
          <p className="text-xs text-text-secondary mt-1">Stand: März 2026</p>
        </div>

        <Section title="1. Geltungsbereich">
          <P>1.1 Diese Allgemeinen Geschäftsbedingungen (nachfolgend «AGB») regeln die Nutzung der Software «OpenFolio» (nachfolgend «Software» oder «Dienst»), bereitgestellt vom Betreiber (siehe <Link to="/impressum" className="text-primary hover:underline">Impressum</Link>).</P>
          <P>1.2 Die AGB gelten für alle Nutzer (nachfolgend «Nutzer» oder «User»), die die Software über den Managed-Hosting-Service des Betreibers nutzen. Für die selbst gehostete Version (Self-Hosted) gelten ausschliesslich die MIT-Lizenzbedingungen.</P>
          <P>1.3 Mit der Registrierung bestätigt der Nutzer, dass er diese AGB gelesen hat, sie versteht und ihnen zustimmt.</P>
          <P>1.4 Der Betreiber behält sich das Recht vor, diese AGB jederzeit zu ändern. Bei wesentlichen Änderungen werden registrierte Nutzer per E-Mail oder In-App-Benachrichtigung informiert und um erneute Zustimmung gebeten. Die weitere Nutzung nach Inkrafttreten unwesentlicher Änderungen gilt als Zustimmung.</P>
        </Section>

        <Section title="2. Beschreibung des Dienstes">
          <P>2.1 OpenFolio ist ein Software-Tool zur Verwaltung und Analyse von Wertpapierportfolios. Die Software bietet unter anderem:</P>
          <ul className="list-disc list-inside text-sm text-text-secondary space-y-1 ml-2">
            <li>Erfassung und Verwaltung von Wertpapieren, ETFs, Kryptowährungen, Edelmetallen, Cash-Konten, Vorsorge und Immobilien</li>
            <li>Berechnung von Portfolio-Performance (XIRR, Modified Dietz)</li>
            <li>Technische Analyseindikatoren (Moving Averages, Mansfield Relative Strength, Donchian Channel, Scoring)</li>
            <li>Marktdaten und Makro-Indikatoren</li>
            <li>Import von Broker-Daten (CSV)</li>
            <li>Alerts und Benachrichtigungen</li>
          </ul>
          <P>2.2 Die Software ist ein <strong className="text-text-primary">Analyse-Werkzeug</strong>. Sie ist <strong className="text-text-primary">kein Anlageberater, kein Finanzintermediär und kein Vermögensverwalter</strong> im Sinne des Schweizer Finanzdienstleistungsgesetzes (FIDLEG) oder vergleichbarer ausländischer Regulierungen.</P>
        </Section>

        <Section title="3. Keine Anlageberatung">
          <P>3.1 <strong className="text-text-primary">OpenFolio gibt keine Anlageberatung und keine Anlageempfehlungen.</strong> Sämtliche in der Software angezeigten Analysen, Scoring-Ergebnisse, Signale, Indikatoren und Bewertungen sind technische Berechnungen auf Basis öffentlich verfügbarer Marktdaten. Sie stellen keine Aufforderung zum Kauf oder Verkauf von Wertpapieren oder anderen Finanzinstrumenten dar.</P>
          <P>3.2 Begriffe wie «Kaufkriterien erfüllt», «Verkaufskriterien erreicht», «Beobachtungsliste», «Makro-Kriterien nicht erfüllt» und ähnliche Bezeichnungen innerhalb der Software beschreiben das Ergebnis technischer Berechnungen. Sie sind <strong className="text-text-primary">keine personalisierten Empfehlungen</strong> und berücksichtigen nicht die individuelle finanzielle Situation, Risikobereitschaft oder Anlageziele des Nutzers.</P>
          <P>3.3 Der Nutzer ist allein für seine Anlageentscheidungen verantwortlich. Der Betreiber empfiehlt, vor jeder Anlageentscheidung einen qualifizierten und unabhängigen Finanzberater zu konsultieren.</P>
          <P>3.4 <strong className="text-text-primary">Vergangene Wertentwicklungen sind kein verlässlicher Indikator für zukünftige Ergebnisse.</strong> Jede Investition in Wertpapiere ist mit Risiken verbunden, einschliesslich des Risikos eines Totalverlusts.</P>
        </Section>

        <Section title="4. Datengenauigkeit und Haftungsausschluss">
          <P>4.1 <strong className="text-text-primary">Keine Gewähr auf Richtigkeit.</strong> Kurse, Finanzdaten, Fundamentalkennzahlen und Marktindikatoren stammen von Drittanbietern (Yahoo Finance, CoinGecko, FRED, Financial Modeling Prep, Schweizerische Nationalbank u.a.). Der Betreiber übernimmt keine Gewähr für die Richtigkeit, Vollständigkeit, Aktualität oder Verfügbarkeit dieser Daten.</P>
          <P>4.2 <strong className="text-text-primary">Performance-Berechnungen sind Annäherungen.</strong> Die in der Software berechneten Performance-Werte (XIRR, Modified Dietz, Monatsrenditen, realisierte Gewinne) basieren auf mathematischen Modellen und können von tatsächlichen Werten abweichen. Sie dienen der persönlichen Analyse und Übersicht.</P>
          <P>4.3 <strong className="text-text-primary">Nicht für steuerliche Zwecke geeignet.</strong> Berechnungen zu realisierten Gewinnen, Verlusten, Dividenden und Performance sind technische Annäherungen. Sie ersetzen nicht die steuerliche Aufstellung durch einen qualifizierten Steuerberater und sind nicht als Grundlage für Steuererklärungen vorgesehen.</P>
          <P>4.4 <strong className="text-text-primary">Alerts und Benachrichtigungen werden nach bestem Bemühen ausgelöst.</strong> Der Betreiber garantiert weder die vollständige noch die rechtzeitige Zustellung von Alerts, Preis-Alarmen oder E-Mail-Benachrichtigungen. Technische Ausfälle, Netzwerkprobleme, Drittanbieter-Störungen oder Verzögerungen können die Zustellung beeinträchtigen. Der Nutzer darf sich nicht ausschliesslich auf Alerts verlassen, um Anlageentscheidungen zu treffen oder Verluste zu begrenzen.</P>
          <P>4.5 <strong className="text-text-primary">Wechselkurse.</strong> Wechselkurse werden von Drittanbietern bezogen und können verzögert sein. Der angezeigte CHF-Wert ausländischer Positionen kann vom tatsächlichen Marktwert abweichen.</P>
        </Section>

        <Section title="5. Haftung">
          <P>5.1 <strong className="text-text-primary">Haftungsausschluss.</strong> Der Betreiber haftet nicht für direkte, indirekte, zufällige, besondere oder Folgeschäden, die sich aus der Nutzung oder der Unmöglichkeit der Nutzung der Software ergeben. Dies gilt insbesondere, aber nicht abschliessend, für:</P>
          <ul className="list-disc list-inside text-sm text-text-secondary space-y-1 ml-2">
            <li>Finanzielle Verluste, die durch Anlageentscheidungen entstehen, die auf Informationen aus der Software basieren</li>
            <li>Finanzielle Verluste durch fehlerhafte, verspätete oder nicht zugestellte Kursdaten, Berechnungen oder Alerts</li>
            <li>Finanzielle Verluste durch falsch berechnete Performance, Renditen oder Steuerdaten</li>
            <li>Schäden durch Ausfälle, Unterbrechungen oder Sicherheitsvorfälle des Dienstes</li>
            <li>Schäden durch fehlerhafte Daten von Drittanbietern</li>
          </ul>
          <P>5.2 <strong className="text-text-primary">Maximale Haftung.</strong> Sofern eine Haftung des Betreibers trotz der vorstehenden Ausschlüsse rechtlich nicht ausgeschlossen werden kann, ist die Gesamthaftung des Betreibers gegenüber dem Nutzer auf den Betrag beschränkt, den der Nutzer in den letzten 12 Monaten vor Eintritt des schadensbegründenden Ereignisses an den Betreiber für die Nutzung der Software bezahlt hat. Bei kostenloser Nutzung beträgt die maximale Haftung CHF 0.</P>
          <P>5.3 <strong className="text-text-primary">Höhere Gewalt.</strong> Der Betreiber haftet nicht für Leistungsstörungen, die durch Umstände ausserhalb seiner zumutbaren Kontrolle verursacht werden, einschliesslich, aber nicht beschränkt auf: Naturkatastrophen, Krieg, Terrorismus, Pandemien, behördliche Massnahmen, Störungen der Telekommunikationsinfrastruktur, Ausfälle von Drittanbieter-Diensten (Datenprovider, Cloud-Infrastruktur), Cyberangriffe und Stromausfälle.</P>
          <P>5.4 Die vorstehenden Haftungsausschlüsse gelten nicht bei vorsätzlichem oder grobfahrlässigem Handeln des Betreibers.</P>
        </Section>

        <Section title="6. Pflichten des Nutzers">
          <P>6.1 Der Nutzer verpflichtet sich, die Software nur für rechtmässige Zwecke zu nutzen.</P>
          <P>6.2 Der Nutzer ist für die Sicherheit seines Kontos verantwortlich, insbesondere für:</P>
          <ul className="list-disc list-inside text-sm text-text-secondary space-y-1 ml-2">
            <li>Die Geheimhaltung seines Passworts</li>
            <li>Die Sicherung seiner MFA-Zugangsdaten (TOTP-Secret und Backup-Codes)</li>
            <li>Die unverzügliche Meldung bei Verdacht auf unbefugten Zugriff</li>
          </ul>
          <P>6.3 Der Nutzer ist allein verantwortlich für die Richtigkeit der von ihm eingegebenen Daten (Positionen, Transaktionen, Kontostände, etc.).</P>
          <P>6.4 Der Nutzer nimmt zur Kenntnis, dass die Software technische Analysewerkzeuge bereitstellt und keine Anlageberatung darstellt (vgl. Ziffer 3).</P>
          <P>6.5 Der Nutzer darf die Software nicht:</P>
          <ul className="list-disc list-inside text-sm text-text-secondary space-y-1 ml-2">
            <li>Für illegale Aktivitäten nutzen (insbesondere Geldwäscherei, Insiderhandel)</li>
            <li>In einer Weise nutzen, die den Betrieb für andere Nutzer beeinträchtigt</li>
            <li>Reverse-engineeren, dekompilieren oder manipulieren (die Open-Source-Lizenz gewährt Einsicht in den Quellcode; Manipulation des gehosteten Dienstes ist untersagt)</li>
          </ul>
        </Section>

        <Section title="7. Konto und Registrierung">
          <P>7.1 Die Nutzung des Managed-Hosting-Service erfordert die Erstellung eines Benutzerkontos mit einer gültigen E-Mail-Adresse und einem sicheren Passwort.</P>
          <P>7.2 Die Aktivierung der Zwei-Faktor-Authentifizierung (MFA/TOTP) ist Pflicht und Voraussetzung für die vollständige Nutzung der Software.</P>
          <P>7.3 Jeder Nutzer darf nur ein Konto führen.</P>
          <P>7.4 Der Betreiber kann die Registrierung nach eigenem Ermessen einschränken (offene Registrierung, Einladungscodes, geschlossener Modus).</P>
        </Section>

        <Section title="8. Verfügbarkeit und Wartung">
          <P>8.1 Der Betreiber bemüht sich um eine hohe Verfügbarkeit der Software, gibt jedoch <strong className="text-text-primary">keine Verfügbarkeitsgarantie</strong> (kein SLA).</P>
          <P>8.2 Geplante Wartungsarbeiten werden nach Möglichkeit angekündigt. Der Betreiber behält sich das Recht vor, die Software jederzeit ohne Vorankündigung für Wartungsarbeiten, Updates oder Sicherheitsmassnahmen vorübergehend ausser Betrieb zu nehmen.</P>
          <P>8.3 Der Betreiber haftet nicht für Ausfälle, Unterbrechungen oder Datenverluste, die durch Wartungsarbeiten, technische Störungen oder Drittanbieter-Ausfälle verursacht werden.</P>
        </Section>

        <Section title="9. Datenschutz">
          <P>9.1 Der Schutz der persönlichen Daten des Nutzers ist dem Betreiber wichtig. Die Einzelheiten der Datenverarbeitung sind in der <Link to="/datenschutz" className="text-primary hover:underline">Datenschutzerklärung</Link> geregelt, die Bestandteil dieser AGB ist.</P>
          <P>9.2 Sensible persönliche Daten (IBAN, Bankverbindungen, Seriennummern, Adressen, Notizen) werden mit AES-256-Verschlüsselung in der Datenbank gespeichert.</P>
          <P>9.3 Der Betreiber hat über das Admin-Panel <strong className="text-text-primary">keinen Zugriff</strong> auf Portfolio-Daten, Kontostände, Transaktionen oder persönliche Finanzinformationen der Nutzer. Admin-Aktionen werden in einem Audit-Log protokolliert.</P>
          <P>9.4 Es werden keine Nutzungsdaten, Tracking-Informationen oder Analytics an Dritte übermittelt. Es werden keine Werbe-Cookies gesetzt.</P>
        </Section>

        <Section title="10. Drittanbieter-Daten">
          <P>10.1 Die Software bezieht Marktdaten von Drittanbietern. Der Betreiber ist nicht verantwortlich für die Daten dieser Anbieter und gibt keine Zusicherungen bezüglich deren Genauigkeit, Vollständigkeit oder Verfügbarkeit.</P>
          <P>10.2 Die Nutzung der Drittanbieter-Daten unterliegt den jeweiligen Nutzungsbedingungen der Anbieter. Der Nutzer nimmt zur Kenntnis, dass die Verfügbarkeit dieser Daten jederzeit ohne Vorankündigung eingeschränkt oder eingestellt werden kann.</P>
          <P>10.3 Aktuelle Drittanbieter: Yahoo Finance (Kursdaten), CoinGecko (Kryptowährungspreise), FRED / Federal Reserve (Makro-Indikatoren), Financial Modeling Prep (US-Fundamentaldaten), Schweizerische Nationalbank (SARON), TradingView (Chart-Widget).</P>
        </Section>

        <Section title="11. Geistiges Eigentum und Open Source">
          <P>11.1 Die Software OpenFolio ist unter der <strong className="text-text-primary">MIT-Lizenz</strong> als Open-Source-Software veröffentlicht. Der Quellcode ist öffentlich einsehbar unter: <a href="https://github.com/dmxch/openfolio" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">github.com/dmxch/openfolio</a></P>
          <P>11.2 Die MIT-Lizenz erlaubt die freie Nutzung, Modifikation und Weiterverbreitung der Software — auch für kommerzielle Zwecke — unter Beibehaltung des Lizenzhinweises.</P>
          <P>11.3 Die Marke «OpenFolio», das Logo und die Domain sind Eigentum des Betreibers. Die Nutzung der Marke für abgeleitete Produkte oder Dienstleistungen erfordert die schriftliche Zustimmung des Betreibers.</P>
          <div className="mt-2 p-3 rounded bg-card-alt text-xs text-text-secondary font-mono leading-relaxed">
            THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
          </div>
        </Section>

        <Section title="12. Preise und Zahlung">
          <P>12.1 Die Nutzung der Open-Source-Software (Self-Hosted) ist kostenlos.</P>
          <P>12.2 Der Managed-Hosting-Service kann kostenlos oder gegen eine monatliche/jährliche Gebühr angeboten werden. Die aktuellen Preise werden auf der Website des Betreibers veröffentlicht.</P>
          <P>12.3 Der Betreiber behält sich das Recht vor, die Preise mit einer Ankündigungsfrist von 30 Tagen zu ändern. Bestehende Abonnements sind bis zum Ende der aktuellen Laufzeit von Preisänderungen nicht betroffen.</P>
          <P>12.4 Rechnungen werden in Schweizer Franken (CHF) ausgestellt. Zahlungen sind innert 30 Tagen fällig, sofern nicht anders vereinbart.</P>
        </Section>

        <Section title="13. Kündigung und Kontolöschung">
          <P>13.1 Der Nutzer kann sein Konto jederzeit und ohne Angabe von Gründen löschen. Die Löschung erfolgt über die Einstellungen in der Software oder per E-Mail-Anfrage an den Betreiber.</P>
          <P>13.2 Bei Kontolöschung werden <strong className="text-text-primary">alle Daten des Nutzers unwiderruflich gelöscht</strong>. Anonymisierte Einträge im Audit-Log bleiben erhalten.</P>
          <P>13.3 Der Betreiber kann Nutzerkonten sperren oder löschen bei:</P>
          <ul className="list-disc list-inside text-sm text-text-secondary space-y-1 ml-2">
            <li>Verstoss gegen diese AGB</li>
            <li>Missbrauch der Software</li>
            <li>Zahlungsverzug (bei kostenpflichtiger Nutzung) nach zweimaliger Mahnung</li>
            <li>Inaktivität von mehr als 24 Monaten (nach vorheriger Ankündigung per E-Mail)</li>
          </ul>
          <P>13.4 Bei kostenpflichtiger Nutzung: Eine Kündigung durch den Nutzer wird zum Ende der bezahlten Laufzeit wirksam. Es besteht kein Anspruch auf anteilige Rückerstattung, es sei denn, zwingendes Recht schreibt dies vor.</P>
        </Section>

        <Section title="14. Open-Source-Beiträge">
          <P>14.1 Beiträge zur Open-Source-Codebase (Pull Requests, Issues, Code) unterliegen den <a href="https://github.com/dmxch/openfolio/blob/main/CONTRIBUTING.md" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">Contribution Guidelines</a> des Projekts.</P>
          <P>14.2 Mit der Einreichung eines Pull Requests erklärt der Beitragende, dass sein Beitrag unter der MIT-Lizenz steht und er die nötigen Rechte daran hält.</P>
        </Section>

        <Section title="15. Schlussbestimmungen">
          <P>15.1 <strong className="text-text-primary">Anwendbares Recht.</strong> Es gilt ausschliesslich schweizerisches Recht unter Ausschluss des Kollisionsrechts und des UN-Kaufrechts (CISG).</P>
          <P>15.2 <strong className="text-text-primary">Gerichtsstand.</strong> Ausschliesslicher Gerichtsstand für alle Streitigkeiten aus oder im Zusammenhang mit diesen AGB ist der Sitz des Betreibers (Schweiz). Vorbehalten bleiben zwingende gesetzliche Gerichtsstände.</P>
          <P>15.3 <strong className="text-text-primary">Salvatorische Klausel.</strong> Sollte eine Bestimmung dieser AGB ganz oder teilweise unwirksam oder undurchführbar sein oder werden, bleibt die Wirksamkeit der übrigen Bestimmungen unberührt.</P>
          <P>15.4 <strong className="text-text-primary">Gesamte Vereinbarung.</strong> Diese AGB, zusammen mit der Datenschutzerklärung und dem Haftungsausschluss (Disclaimer), bilden die gesamte Vereinbarung zwischen dem Betreiber und dem Nutzer in Bezug auf die Nutzung der Software.</P>
          <P>15.5 <strong className="text-text-primary">Verzicht.</strong> Das Unterlassen der Durchsetzung einer Bestimmung dieser AGB durch den Betreiber stellt keinen Verzicht auf diese Bestimmung dar.</P>
        </Section>

        <div className="text-xs text-text-secondary">
          Stand: März 2026
        </div>

        <Section title="Kontakt">
          <P>Bei Fragen zu diesen Nutzungsbedingungen wende dich an den Betreiber (siehe <Link to="/impressum" className="text-primary hover:underline">Impressum</Link>).</P>
        </Section>

        <div className="text-xs text-text-secondary pt-4 border-t border-border space-x-4">
          <Link to="/datenschutz" className="hover:text-text-secondary transition-colors">Datenschutz</Link>
          <Link to="/disclaimer" className="hover:text-text-secondary transition-colors">Disclaimer</Link>
          <Link to="/impressum" className="hover:text-text-secondary transition-colors">Impressum</Link>
        </div>
      </div>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <h3 className="text-sm font-semibold text-text-primary mb-3">{title}</h3>
      <div className="space-y-2">{children}</div>
    </div>
  )
}

function P({ children }) {
  return <p className="text-sm text-text-secondary leading-relaxed">{children}</p>
}
