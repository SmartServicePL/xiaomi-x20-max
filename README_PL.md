# X20 Max (Smart Service) dla Home Assistant

<p align="center">
  <img src="custom_components/xiaomi_x20_max/brand/icon@2x.png"
       alt="Logo integracji X20 Max" width="180">
</p>

Nieoficjalna integracja przeznaczona wyłącznie dla modelu
`xiaomi.vacuum.d109gl`.

Integracja nie jest powiązana z Xiaomi ani przez nią wspierana. Korzysta z
klienta OAuth oficjalnej integracji Xiaomi Home i jest udostępniana na
licencji Xiaomi Home wyłącznie do prywatnego, niekomercyjnego użytku z Home
Assistant (zobacz [LICENSE_XIAOMI.md](LICENSE_XIAOMI.md)). Nazwy produktów
służą tylko do wskazania obsługiwanego urządzenia.

Integracja przygotowana przez **Smart Service**.

## Funkcje

- pełne sterowanie odkurzaczem i stacją Omni;
- ID i nazwy pomieszczeń z aktualnej mapy;
- sensor aktualnej lokalizacji z ostrożnym wykrywaniem pokoju, jeśli robot
  udostępni dane pozycji;
- sprzątanie jednego lub wielu pomieszczeń po ID albo nazwie oraz obsługa
  `vacuum.clean_area`;
- tryb pracy, moc, ilość wody, 1–3 przejazdy i wybór trasy;
- bateria, historia, błędy oraz trwałość materiałów eksploatacyjnych;
- ustawienia dywanów, przeszkód, detergentu i trybu DND;
- przyciski mapowania oraz zerowania liczników;
- zaawansowane usługi surowych właściwości i akcji MIoT;
- polskie i angielskie tłumaczenie.

## Wymagania

- Home Assistant 2026.7.0 lub nowszy;
- Xiaomi Robot Vacuum X20 Max (`xiaomi.vacuum.d109gl`);
- robot dodany do aplikacji Xiaomi Home;
- oficjalna integracja **Xiaomi Home** skonfigurowana w Home Assistant dla
  tego samego konta i regionu — dostarcza pierwszy grant OAuth;
- dostęp HA do `*.ha.api.io.mi.com`.

## Instalacja przez HACS

1. Otwórz **HACS → Integracje → Niestandardowe repozytoria**.
2. Dodaj `https://github.com/SmartServicePL/xiaomi-x20-max` jako
   repozytorium typu **Integracja**.
3. Zainstaluj **Xiaomi Robot Vacuum X20 Max** i uruchom ponownie HA.
4. Wejdź w **Ustawienia → Urządzenia i usługi → Dodaj integrację**.
5. Wyszukaj integrację i wybierz robota.

Jeśli pojawi się błąd OAuth, najpierw skonfiguruj lub przeładuj oficjalną
integrację Xiaomi Home, a następnie spróbuj ponownie.

### Instalacja ręczna

Skopiuj katalog `custom_components/xiaomi_x20_max` do katalogu
`custom_components` w konfiguracji Home Assistant, uruchom HA ponownie i dodaj
integrację z interfejsu.

### Ponowne uwierzytelnienie

Integracja nie ma własnego logowania do Xiaomi — korzysta z logowania
oficjalnej integracji Xiaomi Home. Gdy Xiaomi odrzuci dane OAuth, integracja
najpierw sama pobiera nowsze dane z Xiaomi Home. Jeśli to niemożliwe,
Home Assistant pokaże **Ponowne uwierzytelnienie** dla X20 Max: zaloguj się
ponownie w Xiaomi Home (to samo konto i region), a potem otwórz ponowne
uwierzytelnienie X20 Max i wybierz **Zatwierdź**.

## Sprzątanie pomieszczeń

```yaml
action: xiaomi_x20_max.clean_rooms
data:
  entity_id: vacuum.moj_x20_max_sterowanie
  rooms:
    - Kuchnia
    - 10
  mode: vacuum_and_mop
  suction: turbo
  water_level: medium
  passes: 2
  route: careful
```

ID i nazwy są dostępne w sensorze **Pomieszczenia** i w atrybutach encji
odkurzacza. `rooms` przyjmuje ID, dokładne nazwy albo ich mieszankę. ID są
sprawdzane z aktywną mapą robota; jeśli mapa nie jest wczytana, akcja kończy
się błędem zamiast wysłać niesprawdzone ID.

Akcja czeka na potwierdzenie startu. Robot odpowiada ogólnym kodem MIoT,
który nie mówi, czy sprzątanie ruszyło, więc w takim przypadku integracja
do 5 minut odczytuje status robota i aktywne zadanie, bo przy mopowaniu
robot najpierw przez około 3 minuty myje mopy w stacji. Jeśli robot nie
ruszy (np. brak czystej wody albo problem ze stacją), akcja kończy się
błędem od razu, gdy robot zatrzyma się z kodem usterki. Błąd podaje status
MIoT i kody usterek, więc automatyzacja może na niego zareagować.

Robot zawsze zaczyna sprzątanie od pomieszczenia, w którym stoi stacja:
wyjeżdża ze stacji i od niej planuje trasę, więc pokój ze stacją jest
sprzątany jako pierwszy, nawet jeśli w `rooms` pierwszy jest inny pokój.
Żeby kolejka była przewidywalna, podawaj pokój ze stacją na początku.

W trakcie zadania z mopowaniem robot wraca do stacji na mycie mopów (stan
`returning`) i myje je w stacji (stan `cleaning`). Zadanie jest zakończone,
gdy stan zmieni się na `docked`. Surowy status MIoT jest w atrybucie
`miot_status`.

`mode`, `suction`, `water_level`, `passes` i `route` zmieniają globalne
ustawienia robota i zostają po zakończeniu sprzątania. `vacuum.start`,
`vacuum.clean_area` i harmonogramy w aplikacji Xiaomi Home używają tych
bieżących ustawień, dlatego w każdej automatyzacji, która od nich zależy,
podawaj je jawnie.

## Sprzątanie obszarów (Home Assistant 2026.3+)

Encja odkurzacza obsługuje `vacuum.clean_area`. Obszary Home Assistant
przypisz do pomieszczeń robota w oknie ustawień encji odkurzacza X20 Max.
`clean_area` korzysta z tego samego sprawdzania pomieszczeń i potwierdzania
startu co `clean_rooms` oraz z bieżącego trybu i mocy ssania robota.

Gdy zmienią się pomieszczenia robota (nowa mapa, podział pokoi, przełączenie
mapy), Home Assistant pokaże zgłoszenie naprawy; otwórz je i przypisz
obszary ponownie.

## Akcje stacji

```yaml
action: xiaomi_x20_max.station_action
data:
  entity_id: vacuum.moj_x20_max_sterowanie
  action: wash_mops
```

Dostępne akcje: `empty`, `wash_mops`, `dry_mops`, `leave_station`,
`stop_washing`, `stop_drying` i `return_to_wash`.

## Blueprint powiadomień serwisowych

Opcjonalny blueprint wysyła powiadomienia o problemach stacji, stanie błędu,
niedostępności robota, detergencie, mopach, filtrze, szczotkach i worku na
kurz. Utwórz z niego jedną automatyzację dla każdego robota i wybierz własną
akcję powiadomienia. Powiadomienia przychodzą tylko przy rzeczywistych
zmianach, a nie po powrocie wartości po przerwie w chmurze, restarcie lub
przeładowaniu. Język powiadomień (polski lub angielski) wybiera się w
blueprincie. Alarm materiału eksploatacyjnego przychodzi przy przekroczeniu
progu, więc wartość, która jest już poniżej progu w chwili tworzenia
automatyzacji, nie wyśle powiadomienia.

[Importuj blueprint](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FSmartServicePL%2Fxiaomi-x20-max%2Fblob%2Fmain%2Fblueprints%2Fautomation%2FSmartServicePL%2Fx20_max_maintenance.yaml)

## Prywatność

Integracja jednorazowo importuje grant OAuth oficjalnej integracji Xiaomi
Home, zapisuje go we własnym magazynie HA i później samodzielnie odświeża.
Nie zapisuje hasła konta ani lokalnych tokenów urządzeń. Dane logowania
zostają w Home Assistant i są wysyłane tylko do Xiaomi Cloud. Diagnostyka
ukrywa identyfikator chmurowy urządzenia i nazwy pomieszczeń.

## Ograniczenia

- komunikacja odbywa się przez chmurę Xiaomi;
- obsługiwane jest jedno konto/region Xiaomi na instalację HA;
- dokładne wskazanie aktualnego pokoju zależy od tego, czy Xiaomi Cloud zwróci
  dane pozycji robota. Jeśli chmura zwraca tylko kolejkę sprzątania, sensor
  lokalizacji pokazuje `Nieznane`, a kolejkę udostępnia w atrybutach;
- robot jest niedostępny, gdy Xiaomi Cloud nie odpowiada przez 3 minuty albo
  Xiaomi zgłasza robota jako offline (sprawdzane co 5 minut);
- przyciski **Usuń mapę**, **Automatycznie podziel pomieszczenia** i
  **Rozpocznij szybkie mapowanie** są domyślnie wyłączone, bo zmieniają ID pomieszczeń
  używane w automatyzacjach; w razie potrzeby włącz je w ustawieniach encji;
- brak renderowania mapy;
- model nie udostępnia procentowego poziomu czystej i brudnej wody;
- kody usterek nie mają oficjalnej listy. Opis (`fault_code_description`
  i sensor Błędy) dostają tylko kody o znanym znaczeniu; pozostałe są
  pokazywane jako numer;
- `fault_code` to ostatni kod usterki zgłoszony przez robota (MIoT 2.3).
  Zostaje po ustąpieniu usterki, więc służy tylko do diagnostyki.
  `fault_code_description` ma wartość tylko wtedy, gdy ta usterka jest
  aktywna (kod jest też na bieżącej liście usterek); w przeciwnym razie jest
  pusty;
- część właściwości MIoT jest nieudokumentowana i może zmienić się wraz z
  oprogramowaniem robota.

Usługi `set_property` i `execute_action` są przeznaczone dla zaawansowanych
użytkowników. Błędne wartości mogą zmienić mapy lub ustawienia urządzenia.

## Zgłaszanie problemów

Otwórz [zgłoszenie](https://github.com/SmartServicePL/xiaomi-x20-max/issues)
i dołącz diagnostykę Home Assistant. Nigdy nie dołączaj plików `.storage`
ani tokenów.

## Licencja i zastrzeżenia

Licencja MIT. Projekt nie jest powiązany z Xiaomi. Interfejs Xiaomi Cloud
jest używany wyłącznie w prywatnych, niekomercyjnych instalacjach Home
Assistant; zobacz [LICENSE_XIAOMI.md](LICENSE_XIAOMI.md).
