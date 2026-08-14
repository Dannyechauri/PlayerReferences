from gui import App
import database as db

if __name__ == "__main__":
    db.init_db()
    App().mainloop()
