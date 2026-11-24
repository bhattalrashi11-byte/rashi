from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_admin
from app.models import Building, Floor, Room, CampusNode, CampusEdge
from app.schemas import (
    RoomCreate,
    CampusNodeCreate,
    CampusEdgeCreate,
)
from app.services.graph import CampusGraph

router = APIRouter(
    prefix="/campus",
    tags=["Campus"],
    dependencies=[Depends(get_current_admin)]
)


@router.post("/buildings")
def create_building(
    name: str,
    code: str,
    db: Session = Depends(get_db)
):
    building = Building(name=name, code=code)
    db.add(building)
    db.commit()
    db.refresh(building)
    return building


@router.get("/buildings")
def buildings(db: Session = Depends(get_db)):
    return db.query(Building).all()


@router.post("/floors")
def create_floor(
    building_id: str,
    name: str,
    level: int,
    db: Session = Depends(get_db)
):
    if not db.get(Building, building_id):
        raise HTTPException(404, "Building not found")

    floor = Floor(
        building_id=building_id,
        name=name,
        level=level
    )

    db.add(floor)
    db.commit()
    db.refresh(floor)
    return floor


@router.get("/floors")
def floors(db: Session = Depends(get_db)):
    return db.query(Floor).all()


@router.post("/rooms")
def create_room(
    data: RoomCreate,
    db: Session = Depends(get_db)
):
    if not db.get(Floor, data.floor_id):
        raise HTTPException(404, "Floor not found")

    room = Room(**data.model_dump())
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


@router.get("/rooms")
def rooms(db: Session = Depends(get_db)):
    # Enrich room data with floor and building details
    all_rooms = db.query(Room).all()
    results = []
    for r in all_rooms:
        floor = db.get(Floor, r.floor_id)
        building = db.get(Building, floor.building_id) if floor else None
        # Format human-readable code: e.g. CE-B1-F1-R101
        building_code = building.code if building else "BLD"
        room_code = f"{building_code}-F{floor.level if floor else 1}-{r.name}"
        results.append({
            "id": r.id,
            "code": room_code,
            "name": r.name,
            "room_type": r.room_type.value if hasattr(r.room_type, "value") else str(r.room_type),
            "capacity": r.capacity,
            "floor_id": r.floor_id,
            "floor_name": floor.name if floor else "",
            "floor_level": floor.level if floor else None,
            "building_id": building.id if building else None,
            "building_name": building.name if building else "",
            "available": r.available,
            "equipment": r.equipment or []
        })
    return results


@router.get("/nodes")
def nodes(db: Session = Depends(get_db)):
    return db.query(CampusNode).all()


@router.get("/edges")
def edges(db: Session = Depends(get_db)):
    return db.query(CampusEdge).all()


@router.get("/graph-data")
def graph_data(db: Session = Depends(get_db)):
    """Returns nodes and edges prepared for campus graph visual rendering."""
    all_nodes = db.query(CampusNode).all()
    all_edges = db.query(CampusEdge).all()
    
    node_map = {n.id: n.name for n in all_nodes}

    return {
        "nodes": [
            {
                "id": n.id,
                "name": n.name,
                "node_type": n.node_type,
                "building_id": n.building_id,
                "room_id": n.room_id
            }
            for n in all_nodes
        ],
        "edges": [
            {
                "id": e.id,
                "source_id": e.source_id,
                "source_name": node_map.get(e.source_id, "Node"),
                "target_id": e.target_id,
                "target_name": node_map.get(e.target_id, "Node"),
                "distance": e.distance,
                "connection_type": e.connection_type,
                "bidirectional": e.bidirectional,
                "accessible": e.accessible
            }
            for e in all_edges
        ]
    }


@router.get("/route-between-rooms")
def route_between_rooms(
    source_room_id: str,
    target_room_id: str,
    accessible_only: bool = False,
    db: Session = Depends(get_db)
):
    """
    Computes Dijkstra's shortest path between two classroom locations on campus.
    """
    source_node = db.query(CampusNode).filter(CampusNode.room_id == source_room_id).first()
    target_node = db.query(CampusNode).filter(CampusNode.room_id == target_room_id).first()

    if not source_node or not target_node:
        raise HTTPException(
            404,
            f"Campus graph nodes not mapped for these rooms. Source mapped: {bool(source_node)}, Target mapped: {bool(target_node)}"
        )

    graph = CampusGraph(db)
    graph.load()
    result = graph.shortest_path(source_node.id, target_node.id, accessible_only)

    if not result["reachable"]:
        return {
            "reachable": False,
            "path_names": [],
            "distance": None,
            "estimated_walking_minutes": None
        }

    # Map node IDs to names
    nodes = {n.id: n for n in db.query(CampusNode).all()}
    path_names = [nodes[nid].name if nid in nodes else nid for nid in result["path"]]
    distance = result["distance"]
    # Average walking speed is approx 1.4 m/s (84 m/min)
    estimated_walking_minutes = round(distance / 80.0, 1) if distance is not None else None

    return {
        "reachable": True,
        "source_room_id": source_room_id,
        "target_room_id": target_room_id,
        "path_node_ids": result["path"],
        "path_names": path_names,
        "distance_meters": distance,
        "estimated_walking_minutes": estimated_walking_minutes
    }


@router.post("/nodes")
def create_node(
    data: CampusNodeCreate,
    db: Session = Depends(get_db)
):
    node = CampusNode(**data.model_dump())
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


@router.post("/edges")
def create_edge(
    data: CampusEdgeCreate,
    db: Session = Depends(get_db)
):
    if not db.get(CampusNode, data.source_id):
        raise HTTPException(404, "Source node not found")

    if not db.get(CampusNode, data.target_id):
        raise HTTPException(404, "Target node not found")

    edge = CampusEdge(**data.model_dump())
    db.add(edge)
    db.commit()
    db.refresh(edge)
    return edge


@router.get("/path")
def shortest_path(
    source: str,
    target: str,
    accessible_only: bool = False,
    db: Session = Depends(get_db)
):
    graph = CampusGraph(db)
    graph.load()

    return graph.shortest_path(
        source,
        target,
        accessible_only
    )


@router.get("/nearest-rooms/{source_room_id}")
def nearest_rooms(
    source_room_id: str,
    accessible_only: bool = False,
    db: Session = Depends(get_db)
):
    if not db.get(Room, source_room_id):
        raise HTTPException(404, "Source room not found")

    graph = CampusGraph(db)
    graph.load()

    candidates = db.query(Room).filter(
        Room.available.is_(True)
    ).all()

    return graph.nearest_rooms(
        source_room_id,
        candidates,
        accessible_only
    )