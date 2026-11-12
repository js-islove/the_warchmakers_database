# Simple Frontend Guide (`apps/web`)

We are combining the **best of both worlds**:
1. **Simple, Maintainable Code Architecture:** Plain **React (Vite)** with only **6 core files**—no Next.js server component complexity, no Redux, just clean `useState` and `useEffect`.
2. **Fancy, Sleek Visual UI:** An interactive, zoomable/draggable **React Flow (`@xyflow/react`)** node graph with animated connection lines, dark-mode Swiss watchmaker aesthetic, and color-coded compatibility badges.

---

## 1. Tech Stack

1. **React + Vite:** Fast, clean single-page React app.
2. **React Flow (`@xyflow/react`) + `dagre`:** Renders the **interactive Family Tree Graph** (zoom, pan, mini-map, animated arrows, and clickable movement node cards automatically arranged in a tree).
3. **Tailwind CSS + Lucide Icons:** Gives the website a sleek dark-mode horological dashboard look (`slate-950` canvas, glowing amber/emerald badges, monospace spec readouts).
4. **Standard `fetch()`:** Calls our FastAPI backend (`http://localhost:8000/api/...`).

---

## 2. Simple 6-File Folder Structure

Everything lives in **6 easy-to-read files** inside `apps/web/src/`:

```text
apps/web/
├── index.html
├── package.json
├── vite.config.js
└── src/
    ├── main.jsx                  # Starts the React app
    ├── api.js                    # Simple fetch() functions talking to FastAPI (port 8000)
    ├── App.jsx                   # Main layout: Top Search + Left Movement List + Right Workbench
    └── components/
        ├── FamilyTreeTab.jsx     # Tab 1: Interactive React Flow Graph (Zoomable/Draggable Nodes)
        ├── DonorPartsTab.jsx     # Tab 2: Donor Scavenger Matrix with CS part filter pills
        └── CaseSwapTab.jsx       # Tab 3: Drop-In Case & Hand Swap Calculator with mm deltas
```

---

## 3. How the Screen Looks (Single-Page Workbench)

Everything happens on **one sleek dashboard screen**:

```text
+--------------------------------------------------------------------------------------------------+
|  ⌚ HOROLOGY GRAPH ENGINE       [ Search: 2824, 7750, AS 1525... ]   [Brand v] [Winding]  [DB OK] |
+-----------------------------------+--------------------------------------------------------------+
|  MOVEMENT CATALOG (1,051)         |  SELECTED MOVEMENT WORKBENCH                                 |
|                                   |                                                              |
|  * ETA 2824-2          Automatic  |  ETA 2824-2                              [Current] [25.60mm] |
|    25.6mm • 25J • 28,800 vph      |  ETA SA Manufacture Horlogère Suisse • Automatic • 25 Jewels |
|                                   |                                                              |
|    Sellita SW200-1     Automatic  |  [Diameter: 25.60mm] [Height: 4.60mm] [Beat: 28,800 vph]     |
|    25.6mm • 26J • 28,800 vph      |  [Lift Angle: 50.0°] [Shock: Incabloc] [Hands: 1.50/0.90mm]  |
|                                   |                                                              |
|    Valjoux 7750        Automatic  |  ----------------------------------------------------------  |
|    30.0mm • 25J • 28,800 vph      |  [ 1. Interactive Graph ] [ 2. Donor Parts ] [ 3. Case Swap ]|
|                                   |  ----------------------------------------------------------  |
|    Seiko NH35A         Automatic  |  +--------------------------------------------------------+  |
|    27.4mm • 24J • 21,600 vph      |  |  INTERACTIVE REACT FLOW CANVAS (Zoom / Pan / Click)    |  |
|                                   |  |                                                        |  |
|    A. Schild AS 1525   Manual     |  |         [ ETA 2824 (1971) ]                            |  |
|    25.6mm • 17J • 18,000 vph      |  |                  |  DERIVED_FROM                       |  |
|                                   |  |                  v                                     |  |
|                                   |  |     +---> [ * ETA 2824-2 * ] <---+                     |  |
|                                   |  |     |             |              |                     |  |
|                                   |  |  CLONE_OF    DERIVED_FROM     CLONE_OF                 |  |
|                                   |  |     |             v              |                     |  |
|                                   |  | [SW200-1]    [ETA 2836-2]    [STP 1-11]                |  |
|                                   |  +--------------------------------------------------------+  |
+-----------------------------------+--------------------------------------------------------------+
```

---

## 4. What Each of the 6 Files Does

### 1. `src/api.js` (The Backend Connector)
Contains 5 simple functions that fetch JSON from your FastAPI backend (`http://localhost:8000`):
* `searchMovements({ q, brand, winding, source })` $\rightarrow$ calls `GET /api/search`
* `getMovementDetails(key)` $\rightarrow$ calls `GET /api/calibers/{key}`
* `getFamilyTree(key)` $\rightarrow$ calls `GET /api/calibers/{key}/lineage`
* `getDonorParts(key, partSlot)` $\rightarrow$ calls `GET /api/calibers/{key}/donors`
* `getCaseSwaps(key)` $\rightarrow$ calls `GET /api/calibers/{key}/substitutes`

### 2. `src/App.jsx` (The Main Dashboard)
* Holds `selectedKey` in React state (defaults to `'eta:2824-2'`).
* **Left Sidebar:** Searchable, filterable list of all 1,051 movements + quick-jump buttons for famous families (`ETA 2824`, `Valjoux 7750`, `Seiko NH35`, `AS 1525`).
* **Right Area:** Displays the movement's technical spec cards, Swiss CS parts list, and the 3 interactive tabs.

### 3. `src/components/FamilyTreeTab.jsx` (Tab 1: Interactive React Flow Graph)
* Uses **React Flow (`@xyflow/react`)** + **`dagre`** to render an interactive node graph on a dotted blueprint canvas.
* **Custom Watch Movement Nodes:** Each node is a styled card showing the brand, caliber name, diameter, beat rate, and jewel count. The active movement glows in **amber gold**.
* **Animated Edges:** Solid amber lines for `DERIVED_FROM` (evolutions) and animated dashed cyan lines for `CLONE_OF` (clones).
* **Interactive:** Click any node in the graph to immediately jump to that movement! Includes zoom controls and a mini-map.

### 4. `src/components/DonorPartsTab.jsx` (Tab 2: Donor Scavenger)
* Interactive filter pills at the top (`All Parts`, `Balance Complete CS 721`, `Winding Stem CS 401`, `Mainspring CS 770`, etc.).
* Displays ranked donor cards with visual progress bars for **Part Coverage %** and **Donor Score**, plus color-coded pills for every shared part.

### 5. `src/components/CaseSwapTab.jsx` (Tab 3: Drop-In Substitutes)
* Displays candidate replacement movements with **`Direct Swap` (Green)** or **`Mod Required` (Amber)** badges.
* Shows exact millimeter differences ($\Delta\text{ Diameter}$, $\Delta\text{ Height}$, $\Delta\text{ Stem}$), whether the hands fit, and a watchmaker checklist of any needed adjustments.

---

## 5. How to Run It

1. **Backend (Terminal 1):**
   ```powershell
   uvicorn apps.api.main:app --reload --port 8000
   ```
2. **Frontend (Terminal 2):**
   ```powershell
   cd apps/web
   npm install
   npm run dev
   ```
   Opens at **`http://localhost:5173`**.
