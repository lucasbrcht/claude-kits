// HTML-Datei als PDF drucken, nur mit Bordmitteln von macOS (WebKit), für das Werkzeug pdf_aus_html.
// Aufruf: swift html2pdf.swift <quelle.html> <ziel.pdf> [quer]
// Erfolg: Seitenzahl auf stdout, Exit 0. Fehler: Text auf stderr, Exit 1. Ab macOS 13.3 (shouldPrintBackgrounds).
//
// WebKit rundet die Seitenhöhe beim Druck auf ganze CSS-Pixel ab (A4: 1122 statt 1122,52 px). Eine Vorlage mit
// Seiten von genau 297 mm liefe so um einen Hauch über und bekäme nach jeder Seite eine leere. Deshalb druckt das
// Skript auf Papier mit ZUGABE Punkt mehr Höhe (weniger als etwa 1 pt rundet macOS wieder auf A4) und schneidet danach
// jede Seite oben bündig auf A4 zu. Weg fällt nur der Streifen unter der eigentlichen Seite.
// Gedruckt wird erst in eine Temp-Datei, das Ziel entsteht nur fertig und nie halb. Das PDF trägt im Feld Creator
// die KENNUNG: Daran erkennt pdf.py eigene PDFs, die es ohne Rückfrage ersetzen darf.
import AppKit
import WebKit
import PDFKit

func abbruch(_ text: String) -> Never {
    FileHandle.standardError.write((text + "\n").data(using: .utf8)!)
    exit(1)
}

let args = CommandLine.arguments
guard args.count >= 3 else { abbruch("Aufruf: html2pdf <quelle.html> <ziel.pdf> [quer]") }
let src = URL(fileURLWithPath: args[1])
let dst = URL(fileURLWithPath: args[2])
let quer = args.count > 3 && args[3] == "quer"
let KENNUNG = "Claude Kits html2pdf"  // gleich wie KENNUNG in pdf.py
let temp = FileManager.default.temporaryDirectory.appendingPathComponent("html2pdf-\(UUID().uuidString).pdf")

// A4 in Punkt (Druck) und in CSS-Pixeln (Layout)
let a4 = quer ? NSSize(width: 841.89, height: 595.28) : NSSize(width: 595.28, height: 841.89)
let ZUGABE: CGFloat = 1.5
let papier = NSSize(width: a4.width, height: a4.height + ZUGABE)
let rahmen = quer ? NSRect(x: 0, y: 0, width: 1123, height: 794) : NSRect(x: 0, y: 0, width: 794, height: 1123)

let app = NSApplication.shared
app.setActivationPolicy(.prohibited)

final class Job: NSObject, WKNavigationDelegate {
    lazy var web: WKWebView = {
        let cfg = WKWebViewConfiguration()
        cfg.preferences.shouldPrintBackgrounds = true
        return WKWebView(frame: rahmen, configuration: cfg)
    }()
    lazy var win = NSWindow(contentRect: rahmen, styleMask: [.borderless], backing: .buffered, defer: false)

    func start() {
        win.contentView = web
        web.navigationDelegate = self
        web.loadFileURL(src, allowingReadAccessTo: src.deletingLastPathComponent())
        // Sicherung: nach 60 Sekunden abbrechen
        DispatchQueue.main.asyncAfter(deadline: .now() + 60) {
            try? FileManager.default.removeItem(at: temp)
            abbruch("Zeitüberschreitung")
        }
    }

    func webView(_ w: WKWebView, didFinish n: WKNavigation!) {
        // Warten, bis Schriften geladen sind, dann kurz für Bilder
        w.callAsyncJavaScript("await document.fonts.ready\nreturn true", arguments: [:], in: nil, in: .page) { _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { self.drucken() }
        }
    }

    func webView(_ w: WKWebView, didFail n: WKNavigation!, withError e: Error) {
        abbruch("Laden fehlgeschlagen: \(e.localizedDescription)")
    }

    func webView(_ w: WKWebView, didFailProvisionalNavigation n: WKNavigation!, withError e: Error) {
        abbruch("Laden fehlgeschlagen: \(e.localizedDescription)")
    }

    func drucken() {
        let info = NSPrintInfo()
        info.paperSize = papier
        info.orientation = quer ? .landscape : .portrait
        info.topMargin = 0
        info.bottomMargin = 0
        info.leftMargin = 0
        info.rightMargin = 0
        info.horizontalPagination = .automatic
        info.verticalPagination = .automatic
        info.jobDisposition = .save
        info.dictionary().setObject(temp, forKey: NSPrintInfo.AttributeKey.jobSavingURL as NSCopying)
        let op = web.printOperation(with: info)
        op.showsPrintPanel = false
        op.showsProgressPanel = false
        op.view?.frame = rahmen
        op.runModal(for: win, delegate: self, didRun: #selector(fertig(_:success:contextInfo:)), contextInfo: nil)
    }

    @objc func fertig(_ op: NSPrintOperation, success: Bool, contextInfo: UnsafeMutableRawPointer?) {
        // exit() überspringt defer, deshalb räumt jeder Ausgang die Temp-Datei selbst weg
        func weg() { try? FileManager.default.removeItem(at: temp) }
        guard success, let pdf = PDFDocument(url: temp), pdf.pageCount > 0 else { weg(); abbruch("Druck fehlgeschlagen") }
        for i in 0..<pdf.pageCount {
            guard let seite = pdf.page(at: i) else { continue }
            let roh = seite.bounds(for: .mediaBox)
            // PDF zählt von unten: oben bündig auf A4, der Streifen ganz unten fällt weg
            let a4box = NSRect(x: roh.minX, y: roh.maxY - a4.height, width: a4.width, height: a4.height)
            seite.setBounds(a4box, for: .mediaBox)
            seite.setBounds(a4box, for: .cropBox)
        }
        // Kennung im Feld Creator: pdf.py ersetzt ein PDF mit dieser Kennung ohne Rückfrage, fremde nur mit ersetzen
        var info = pdf.documentAttributes ?? [:]
        info[PDFDocumentAttribute.creatorAttribute] = KENNUNG
        pdf.documentAttributes = info
        let geschrieben = pdf.write(to: dst)
        weg()
        guard geschrieben else { abbruch("PDF nicht schreibbar: \(dst.path)") }
        print(pdf.pageCount)
        exit(0)
    }
}

let job = Job()
job.start()
app.run()
