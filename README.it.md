# MGU Assistant

Un programma per **Windows 11 x64**, con interfaccia in italiano, che accompagna nei controlli della head unit **MGU con iDrive 7**, nell'accesso SSH e nell'installazione di [MGU Store](https://github.com/robertnisipeanu/mgu-store) tramite ENET. [English documentation](README.md).

**Versione pubblica beta: `v0.2.0-beta.2`. La compatibilità con tutte le BMW iDrive 7 non è dimostrata.** Conta la head unit effettivamente montata, con le sue versioni software, non soltanto il modello dell'auto. È disponibile un solo resoconto positivo del proprietario su BMW F44. Leggi [compatibilità](docs/compatibility.md) prima di procedere.

Il progetto è indipendente: non è un prodotto BMW e non è approvato da BMW o dagli autori dei progetti utilizzati. Non garantisce un'installazione senza rischi, la copertura della garanzia o il funzionamento di ogni dotazione.

## Scaricare e provare il programma

1. Apri la pagina [Release](https://github.com/IvanBiondi/mgu-assistant/releases) e scarica lo ZIP Windows x64 della versione scelta. Le beta sono indicate come **Pre-release**.
2. Confronta il valore SHA-256 dello ZIP con quello pubblicato nella release. In PowerShell puoi usare `Get-FileHash -Algorithm SHA256 .\<nome-del-file>.zip`, sostituendo il nome del file.
3. Estrai **tutto lo ZIP** in una cartella locale. Mantieni insieme il programma e le cartelle contenute nel pacchetto; non avviarlo direttamente dallo ZIP.
4. Avvia `DEMO.cmd` per conoscere i pulsanti usando dati simulati. La demo non opera sull'auto e blocca le scritture.
5. Per eseguire scritture sulla vettura, fai clic destro su `MGU-Assistant.exe`, scegli **Esegui come amministratore** e segui i passaggi qui sotto. La demo e i controlli locali del PC non richiedono privilegi di amministratore.

La versione portatile include Python. L'eseguibile **non ha una firma digitale**. Il checksum permette di confrontare i byte scaricati con quelli pubblicati; non certifica il produttore, la sicurezza del programma o la compatibilità della HU. Non disattivare le protezioni di Windows per avviarlo: il codice è disponibile anche per revisione e compilazione.

## Prima di andare in macchina

Prepara:

- Un PC Windows 11 x64, alimentato e senza sospensione automatica durante le operazioni, con **Client OpenSSH di Windows** disponibile.
- Un cavo ENET e una scheda Ethernet funzionanti.
- Una fonte di alimentazione stabilizzata adeguata alla programmazione della vettura, secondo le esigenze del veicolo.
- La **chiave fisica** dell'auto.
- Il backup originale corretto del coding **HU_MGU**, esportato prima di modificare la vettura, e una procedura di ripristino che sai utilizzare.

Il backup BimmerCode va creato ed esportato **manualmente**: consulta il [manuale BimmerCode](https://bimmercode.app/manual/). Conservane anche una copia separata dal PC di lavoro. Selezionare un file nel programma serve a indicare dove si trova: non verifica che sia completo, corretto o ripristinabile.

Verifica autonomamente che la vettura abbia **HU_MGU e iDrive 7**. Il programma usa il percorso `id7` del progetto root. Non supporta NBT, NBT EVO, iDrive 6, iDrive 8 o iDrive 9. Il controllo BTLD `00003F36` è un filtro iniziale, non una certificazione di compatibilità della versione software.

**Il flash root modifica il software della HU, può cancellare il coding e le associazioni Digital Key e può rendere inutilizzabile la HU se interrotto o incompatibile.** Il backup coding non ripristina le associazioni Digital Key. Opera soltanto su una vettura tua o per la quale sei autorizzato, sempre ferma. Durante una scrittura non scollegare alimentazione o ENET, non chiudere l'app e non sospendere il PC.

## Quando sei in macchina: procedura completa

Questa sequenza è per una prima installazione su una configurazione la cui compatibilità sia già stata verificata. **Se SSH è già aperto o hai già tentato il flash, parti dal recupero descritto più sotto.** Nessuna operazione sull'auto parte all'apertura del programma.

### 1. Collega e leggi la HU

1. Metti l'auto nelle condizioni richieste per la procedura, ferma e con alimentazione stabile. Tieni la chiave fisica disponibile.
2. Collega il cavo ENET alla vettura e alla scheda Ethernet del PC.
3. Apri la sezione **Connessione** e premi **Controlla PC e schede**.
4. Seleziona la scheda collegata a ENET. Un indirizzo `169.254.x.x` da solo non dimostra che sia quella corretta: controlla anche il nome della scheda e il collegamento fisico.
5. Premi **Leggi la HU**. Verifica vettura, identificativi e versioni HU e stato SSH. Conserva privatamente il risultato.
6. Se i dati sono inattesi, mancano oppure la compatibilità è incerta, fermati prima delle scritture.

Questo controllo legge le informazioni disponibili; non certifica l'intero stato della vettura. La porta SSH aperta non dimostra che una chiave consenta l'accesso root.

### 2. Conferma backup e condizioni

1. Apri **Backup e sblocco**.
2. Premi **Seleziona file backup…** o **Seleziona cartella…** e indica il backup originale esportato.
3. Spunta le conferme soltanto se vere: backup utilizzabile e ripristino conosciuto; HU_MGU/iDrive 7 e versione verificati; alimentazione stabile e PC senza sospensione; chiave fisica disponibile.

Il programma non produce un backup completo dell'auto e non sostituisce BimmerCode. Se non hai il backup corretto, non proseguire.

### 3. Prima preparazione root, solo quando applicabile

1. **Flash + Enable…** è una scrittura sulla HU. Usalo soltanto per la prima procedura prevista su un'unità compatibile, senza un tentativo di flash già completato o interrotto.
2. Leggi il riepilogo, controlla l'identità della vettura e inserisci il VIN richiesto dal programma.
3. Conferma solo dopo aver ricontrollato alimentazione, ENET e backup.
4. Attendi il risultato senza interrompere. Il programma registra l'avvio della scrittura per impedire una ripetizione accidentale.

**Un errore al termine non significa che il flash non sia avvenuto.** Se qualcosa si interrompe, leggi la fase raggiunta e segui [risoluzione problemi](docs/troubleshooting.md). Non rilanciare il flash e non cancellare lo storico per sbloccare il pulsante.

### 4. Ripristina il coding e controlla le funzioni originali

Dopo un flash completato, ripristina manualmente tramite BimmerCode il backup originale corretto della HU_MGU quando necessario. Questa operazione avviene fuori dall'assistente e va eseguita secondo la procedura BimmerCode.

Verifica che schermo e menu siano tornati operativi e controlla le funzioni originali. Torna nel programma e fai una nuova **Leggi la HU**. Se il ripristino non riesce o mancano funzioni originali, fermati e chiedi assistenza per il coding: non tentare un altro flash come rimedio.

### 5. Seleziona la chiave e verifica l'accesso root

1. Apri **Chiave e coding**.
2. Se hai già il file della chiave privata corretta, premi **Seleziona id_rsa…**.
3. Se la procedura usa la chiave originale dell'immagine debug upstream e manca soltanto il file sul PC, premi **Recupera chiave originale sul PC**. È una copia locale di una chiave **condivisa**, non l'estrazione di una chiave unica dalla tua auto.
4. Premi **Leggi impronta HU…**. Al primo collegamento ENET diretto assicurati che la HU sia quella desiderata e, se hai un riferimento indipendente, confronta l'impronta prima di confermare.
5. Premi **Verifica accesso root**. Il controllo deve autenticarsi correttamente e verificare UID `0`.

La prima accettazione dell'impronta è un meccanismo di fiducia al primo uso: non certifica da sola l'identità della HU. Se in seguito l'impronta cambia, indaga il motivo; non cancellare alla cieca l'identità salvata. La chiave root, la chiave del certificato di enrollment e l'impronta del server sono elementi diversi.

### 6. Completa la persistenza SSH, se manca

Dopo aver ripristinato il coding quando necessario e controllato le funzioni originali, spunta la relativa conferma. Se la procedura iniziale non aveva già completato la persistenza, premi **Completa persistenza SSH…**.

Questa operazione modifica servizi della HU e disattiva il debug usando la procedura upstream fissata dal pacchetto. **Non è un controllo in sola lettura.** Non ripete flash o enrollment e non riavvia automaticamente. Attendi il risultato prima di procedere.

### 7. Installa MGU Store

1. Apri **Installa Store** e premi **Verifica file del pacchetto**.
2. Se un controllo SHA-256 fallisce, fermati: non modificare il valore atteso per superare il controllo.
3. Leggi l'opzione **Includi Internet uplink** e scegli se includere il componente previsto dal progetto.
4. Premi **Installa MGU Store…**, leggi la conferma e avvia l'installazione.
5. Attendi il risultato. Questa fase copia componenti locali e modifica file e servizi della HU; non esegue un nuovo flash root.

L'installazione offline non fornisce automaticamente Internet alla vettura. Per app e aggiornamenti online configura una connessione supportata nelle impostazioni dello Store seguendo il progetto upstream. La connessione Internet del PC non equivale alla connessione Internet della HU.

### 8. Riavvia e verifica

1. Dopo il completamento delle operazioni precedenti, apri **Riavvio e verifica**.
2. Premi **Riavvia la HU…** e conferma soltanto a vettura ferma.
3. Attendi che iDrive torni disponibile.
4. Controlla menu, audio, telecamere, sensori e le altre funzioni originali effettivamente presenti sull'auto.
5. Apri MGU Store e verifica le app. Ripeti i controlli al successivo normale avvio della vettura.

Il programma non garantisce funzioni come Waze nel quadro strumenti, nuovi equipaggiamenti o integrazioni CarPlay che dipendono da hardware e software specifici.

## Se hai già fatto il flash o SSH è già aperto

Non ripartire dal pulsante **Flash + Enable…**. Esegui una nuova lettura della HU, verifica/ripristina il coding e le funzioni originali, seleziona o recupera localmente la chiave corretta, conferma l'impronta e verifica l'accesso root. Completa soltanto la persistenza eventualmente mancante, poi installa lo Store e riavvia con il pulsante separato.

Nella prima installazione riportata dal proprietario, il flash era arrivato a **174/174**, ma un controllo successivo aveva ricevuto `7F 22 21` (`busyRepeatRequest`). Il proprietario ha ripristinato il backup BimmerCode; SSH risultava già aperto. Il recupero è avvenuto senza rifare il flash. Questo singolo caso non dimostra che ogni errore o schermo bloccato abbia la stessa causa: [leggi i dettagli](docs/troubleshooting.md).

## Dati locali, chiavi e riservatezza

Lo stato locale si trova normalmente in `%LOCALAPPDATA%\MGUAssistant` e può contenere identificativi della vettura, percorsi delle chiavi, impronte accettate e registro delle scritture. Mantienilo privato e preservalo quando aggiorni o sposti l'app. Cancellare lo stato non annulla le modifiche sulla HU.

Il registro protegge i tentativi registrati sullo stesso PC e nella stessa cartella di stato. Non può rilevare tentativi fatti con vecchie versioni, un altro PC o un'altra cartella di stato. Non cancellare o cambiare lo stato per forzare un nuovo tentativo: verifica prima la situazione effettiva della HU.

Non pubblicare chiavi private, backup, VIN, schermate con identificativi o log integrali. La chiave bootstrap originale è condivisa: la generazione/provisioning di una chiave unica per ogni auto non è implementata da questo assistente.

Il componente privacy incluso modifica alcune modalità di segnalazione secondo il proprio progetto. Non garantisce invisibilità, anonimato completo o assenza di conseguenze sull'assistenza.

## Eseguire e compilare dai sorgenti

Su Windows usa Python 3.12 con Tkinter:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/prepare_resources.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py --demo
.\.venv\Scripts\python.exe scripts/build.py
.\.venv\Scripts\python.exe scripts/package.py
```

La preparazione richiede Internet. Il repository contiene sorgenti e metadati delle risorse fissate, non eseguibili upstream, chiavi private o dati di auto. `prepare_resources.py` prepara le risorse previste nelle cartelle escluse da Git e ne controlla SHA-256; `build.py` prepara l'applicazione e `package.py` crea lo ZIP e il checksum nella cartella `release/`.

Un file dell'installer upstream è cambiato dopo il download originale: i controlli CI hanno rilevato la differenza SHA-256. Per rendere riproducibile la compilazione, il pacchetto originale verificato delle risorse è conservato anche nella release [resources-20261105](https://github.com/IvanBiondi/mgu-assistant/releases/tag/resources-20261105) di questo repository. Quando manca la cache locale, la preparazione usa questo archivio verificandone il checksum. Gli URL delle fonti ufficiali e i valori SHA-256 originali restano registrati; la copia non sostituisce i crediti o le licenze upstream. I controlli restano obbligatori: i valori attesi non sono stati modificati per accettare l'installer cambiato.

I test automatici e la CI usano controlli locali e risposte simulate: **non operano su una vettura** e non dimostrano la compatibilità con altri modelli. Consulta anche [compatibilità](docs/compatibility.md), [problemi noti](docs/troubleshooting.md), [contributi](CONTRIBUTING.md) e [segnalazioni di sicurezza](SECURITY.md).

## Crediti e licenze

- [cauliflowermossgrape/idrive7-8-ssh-root](https://github.com/cauliflowermossgrape/idrive7-8-ssh-root): root, enrollment e persistenza; l'assistente espone soltanto il percorso `id7`.
- [robertnisipeanu/mgu-store](https://github.com/robertnisipeanu/mgu-store): Store e componenti, con licenza GPL-3.0-or-later e le eventuali licenze specifiche dei componenti.

Il codice originale dell'assistente è distribuito con [licenza MIT](LICENSE). Le dipendenze mantengono le proprie licenze: MIT non sostituisce quelle upstream. Le distribuzioni devono mantenere gli avvisi e i riferimenti ai sorgenti inclusi.
