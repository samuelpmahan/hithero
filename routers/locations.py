"""State, county, district and school lists for the dropdowns."""


from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db import get_db
from repositories import schools, teachers

router = APIRouter()


#api gets a list of states from statecoutny table
@router.get("/api/get_states/")
async def get_states(db: Session = Depends(get_db)):
    return sorted(schools.list_states(db))

#api gets the names of the counties in the desired state
@router.get("/api/get_counties/{state}")
async def get_counties(state: str, db: Session = Depends(get_db)):
    counties = schools.list_counties(db, state)
    if counties:
        return sorted(counties)
    else:
        return {"message": f"No counties found for state: {state}"}

#api gets the names of the school districts in the desired county and state
@router.get("/api/get_districts/{state}/{county}")
async def get_districts(state: str, county: str, db: Session = Depends(get_db)):
    districts = schools.list_districts(db, state, county)
    if districts:
        return sorted(districts)
    else:
        return {"message": f"No districts found for state: {state} and county: {county}"}

#api gets the names of the school in the desired district, coutny, and state
@router.get("/api/get_schools/{state}/{county}/{district}")
async def get_schools(state: str, county: str, district: str, db: Session = Depends(get_db)):
    school_names = schools.list_schools(db, state, county, district)
    if school_names:
        return sorted(school_names)
    else:
        return {"message": f"No schools found for state: {state}, county: {county}, and district: {district}"}


#api gets a list of states from statecoutny table
@router.get("/api/index_states/")
async def index_states(db: Session = Depends(get_db)):
    return sorted(teachers.index_states(db))

#api gets the names of the counties in the desired state
@router.get("/api/index_counties/{state}")
async def index_counties(state: str, db: Session = Depends(get_db)):
    counties = teachers.index_counties(db, state)
    if counties:
        return sorted(counties)
    else:
        return {"message": f"No counties found for state: {state}"}

#api gets the names of the school districts in the desired county and state
@router.get("/api/index_districts/{state}/{county}")
async def index_districts(state: str, county: str, db: Session = Depends(get_db)):
    districts = teachers.index_districts(db, state, county)
    if districts:
        return sorted(districts)
    else:
        return {"message": f"No districts found for state: {state} and county: {county}"}

#api gets the names of the school in the desired district, coutny, and state
@router.get("/api/index_schools/{state}/{county}/{district}")
async def index_schools(state: str, county: str, district: str, db: Session = Depends(get_db)):
    school_names = teachers.index_schools(db, state, county, district)
    if school_names:
        return sorted(school_names)
    else:
        return {"message": f"No schools found for state: {state}, county: {county}, and district: {district}"}
