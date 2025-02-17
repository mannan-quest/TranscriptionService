class NotesService:
    def __init__(self, notes_repository):
        self.notes_repository = notes_repository

    def get_notes(self):
        return self.notes_repository.get_notes()

    def add_note(self, note):
        self.notes_repository.add_note(note)

    def delete_note(self, note_id):
        self.notes_repository.delete_note(note_id)

    def update_note(self, note_id, note):
        self.notes_repository.update_note(note_id, note)