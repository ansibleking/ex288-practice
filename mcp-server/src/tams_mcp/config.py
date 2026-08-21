from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    tams_base_url: str = "https://tams.emaratech.ae"
    tams_auth_mode: str = "tams_login"
    tams_api_scope: str = ""
    tams_access_token: str = ""

    # Connect_API login context (from portal / HR admin)
    tams_username: str = ""
    tams_password: str = ""
    tams_paycode: str = ""
    tams_company_code: str = ""
    tams_auth_comp: str = ""
    tams_auth_dept: str = ""
    tams_auth_loc: str = ""
    tams_auth_site: str = ""
    tams_user_type: str = "ESS"

    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""

    swagger_spec_path: str = "swagger.json"
    swagger_max_tools: int = 60
    swagger_include_tags: str = (
        "login,DailyReports,MonthlyReports,LeaveReports,AttendanceCorrection,Employee,LeaveApplication"
    )


def get_settings() -> Settings:
    return Settings()
