import re
import requests
from bs4 import BeautifulSoup

class AscenderPortalClient:
    def __init__(self, district_id="", username="", password=""):
        self.district_id = district_id
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.is_authenticated = False
        self.csrf_token = None

    def login(self):
        if not self.username or not self.password:
            return False, "Missing Ascender username or password"

        login_url = f"https://portals11.ascendertx.com/ParentPortal/login?distid={self.district_id}"
        try:
            resp = self.session.get(login_url, timeout=15)
            if resp.status_code != 200:
                return False, f"Failed to reach portal: HTTP {resp.status_code}"

            soup = BeautifulSoup(resp.text, "html.parser")
            csrf_meta = soup.find("meta", {"name": "_csrf"})
            self.csrf_token = csrf_meta["content"] if csrf_meta else None
            if not self.csrf_token:
                csrf_input = soup.find("input", {"name": "_csrf"})
                self.csrf_token = csrf_input["value"] if csrf_input else None

            if not self.csrf_token:
                return False, "Failed to retrieve CSRF token from portal"

            post_data = {
                "username": self.username,
                "password": self.password,
                "_csrf": self.csrf_token
            }

            post_url = "https://portals11.ascendertx.com/ParentPortal/loginPP"
            login_resp = self.session.post(post_url, data=post_data, allow_redirects=True, timeout=15)

            if "login" in login_resp.url.lower() and "loginPP" not in login_resp.url:
                err_soup = BeautifulSoup(login_resp.text, "html.parser")
                alert = err_soup.find(class_=re.compile(r"alert|error"))
                msg = alert.get_text(strip=True) if alert else "Invalid username or password"
                self.is_authenticated = False
                return False, msg

            self.is_authenticated = True
            return True, None
        except Exception as e:
            self.is_authenticated = False
            return False, str(e)

    def get_students(self):
        """Discovers all students linked to the parent account."""
        if not self.is_authenticated:
            ok, err = self.login()
            if not ok:
                raise RuntimeError(f"Login failed: {err}")

        # Visit assignments page to establish module context & get page CSRF
        assign_page = self.session.get("https://portals11.ascendertx.com/ParentPortal/assignments", timeout=15)
        soup = BeautifulSoup(assign_page.text, "html.parser")

        csrf_meta = soup.find("meta", {"name": "_csrf"})
        if csrf_meta:
            self.csrf_token = csrf_meta["content"]
            self.session.headers["X-CSRF-TOKEN"] = self.csrf_token
        self.session.headers["X-Requested-With"] = "XMLHttpRequest"

        students = []
        for btn in soup.select("button.selectstudentbyid"):
            s_id = btn.get("data-id")
            s_name = btn.get_text(strip=True)
            if s_id and s_name:
                students.append({
                    "student_id": s_id.strip(),
                    "student_name": s_name.strip()
                })

        # Fallback if active student button doesn't have text inside
        if not students:
            active_name_el = soup.find(id="selectedstudentname")
            active_pic = soup.find(id="selected-student-picture")
            if active_name_el and active_pic:
                pic_style = active_pic.get("style", "")
                m = re.search(r"/getStudentPicture/(\d+)", pic_style)
                s_id = m.group(1) if m else "default"
                students.append({
                    "student_id": s_id,
                    "student_name": active_name_el.get_text(strip=True)
                })

        return students

    def get_assignments(self, student_id):
        """Fetches all assignments for a specific student via Ascender's JSON endpoint."""
        if not self.is_authenticated:
            ok, err = self.login()
            if not ok:
                raise RuntimeError(f"Login failed: {err}")

        # Switch active student in session
        select_params = {
            "pCourseID": "All",
            "pCycle": "1",
            "studentId": student_id
        }
        self.session.get("https://portals11.ascendertx.com/ParentPortal/assignments/selectStudent", params=select_params, timeout=15)

        # Query all assignments
        find_params = {
            "pCourseID": "All",
            "pCycle": "All",
            "view": "0",
            "pMaxDueDate": "",
            "pIncludeBlankDueDates": "true"
        }
        resp = self.session.get("https://portals11.ascendertx.com/ParentPortal/assignments/findAssignments", params=find_params, timeout=20)

        if resp.status_code != 200:
            raise RuntimeError(f"findAssignments failed with HTTP {resp.status_code}")

        data = resp.json()
        if str(data.get("code")) != "1":
            raise RuntimeError(f"findAssignments returned error code: {data.get('code')}")

        raw_list = data.get("data", [])
        clean_assignments = []
        for item in raw_list:
            clean_assignments.append({
                "course": (item.get("course") or "").strip(),
                "assignment": (item.get("assignment") or "").strip(),
                "category": (item.get("category") or "").strip(),
                "due_date": (item.get("dueDate") or "").strip(),
                "grade": (str(item.get("grade") or "")).strip(),
                "failing_grade": bool(item.get("failingGrade")),
                "assignment_note": (item.get("assignmentNote") or "").strip()
            })
        return clean_assignments
