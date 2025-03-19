import asyncio
import os
from typing import List
import PyPDF2
from fastapi import UploadFile
from supabase import create_client

from app.services.translation_service import TranslationAnalysisService


class LectureMaterialNotes:
    def __init__(self, lecture_material_id, file_path, filetype):
        self.lecture_material_id = lecture_material_id
        self.file_path = file_path
        self.filetype = filetype
        self.SUPABASE_URL = os.getenv("SUPABASE_URL")
        self.SUPABASE_KEY = os.getenv("SUPABASE_KEY")
        self.supabase = create_client(self.SUPABASE_URL, self.SUPABASE_KEY)

    def analyze_material(self):
        # Analyze the lecture material and route the material to the appropriate function
        # based on the type of material (e.g., txt, pdf, docx, etc.)
        if self.filetype == 'pdf':
            return self.process_pdf()
        else:
            raise Exception(f"Unsupported file type: {self.filetype}")

    async def process_pdf(self):
        """Process the PDF and update 'progress' column as each step completes."""
        try:
            def update_progress(value: float):
                self.supabase.table("lecture_materials") \
                    .update({"progress": value}) \
                    .eq("material_id", self.lecture_material_id) \
                    .execute()

            # 1) Extract text from PDF
            text_content = self.extract_text_from_pdf()
            if not text_content:
                raise Exception("Could not extract text from PDF")
            update_progress(0.2)  # 20% done

            # 2) Split text into paragraphs
            paragraphs = self.split_into_paragraphs(text_content)
            update_progress(0.3)  # 30% done
            
            # 3) Analyze text content
            translation_service = TranslationAnalysisService()
            analysis = await translation_service.analyze_pdf_text(paragraphs)
            print("Analysis")
            print(analysis)
            update_progress(0.5)  # 50% done

            # 4) Insert notes
            print("Inserting notes")
            self.supabase.table("lecture_materials").update({
                "notes": analysis
            }).eq("material_id", self.lecture_material_id).execute()
            update_progress(0.9)  # 90% done
            
            # 11) Mark done
            update_progress(1.0)  # 100% done
            print(f"PDF processing completed for lecture {self.lecture_material_id}")

        except Exception as e:
            # If something fails, update the DB accordingly
            self.supabase.table("lectures").update({
                "error": str(e),
                "progress": 0.0  # Reset or keep partial progress
            }).eq("lecture_id", self.lecture_material_id).execute() 
            print(f"Error processing PDF lecture {self.lecture_material_id}: {e}")
            raise e
        finally:
            # Clean up temporary file
            if os.path.exists(self.file_path):
                os.remove(self.file_path)

    def extract_text_from_pdf(self):
        # Extract text from a PDF file
        try:
            print(f"Extracting text from PDF: {self.file_path}")
            print(f"File size: {os.path.getsize(self.file_path)} bytes")
            with open(self.file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text = ""
                print(f"Number of pages: {len(pdf_reader.pages)}")
                # Extract text from each page
                for page_num in range(len(pdf_reader.pages)):
                    page = pdf_reader.pages[page_num]
                    text += page.extract_text() + "\n\n"
                    
                return text.strip()
        except Exception as e:
            print(f"Error extracting text from PDF: {e}")
            return ""
            
    def split_into_paragraphs(self,text: str) -> List[str]:
        """Split text into logical paragraphs."""
        # First split by double newlines which typically indicate paragraphs
        initial_split = [p.strip() for p in text.split('\n\n') if p.strip()]
        
        paragraphs = []
        for block in initial_split:
            # Further split long blocks if they contain single newlines
            if len(block) > 500 and '\n' in block:
                sub_paragraphs = [p.strip() for p in block.split('\n') if p.strip()]
                paragraphs.extend(sub_paragraphs)
            else:
                paragraphs.append(block)
        
        return paragraphs